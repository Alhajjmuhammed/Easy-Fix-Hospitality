import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import {
  View,
  SectionList,
  ScrollView,
  StyleSheet,
  Image,
  TouchableOpacity,
} from 'react-native';
import {
  Text,
  Searchbar,
  Chip,
  IconButton,
  Button,
  ActivityIndicator,
  Surface,
  useTheme,
  Snackbar,
  Divider,
  Badge,
} from 'react-native-paper';
import NetInfo from '@react-native-community/netinfo';
import { apiMenu } from '../../api/menu';
import { getCategories, saveCategories, getSyncMeta } from '../../database/operations';
import { useCartStore } from '../../store/useCartStore';
import { MENU_STALE_THRESHOLD_MS } from '../../config';
import { useCurrency } from '../../hooks/useCurrency';

export default function MenuScreen({ navigation }) {
  const theme = useTheme();
  const { items, addItem, getItemCount, getSubtotal } = useCartStore();
  const { format } = useCurrency();

  const [categories, setCategories] = useState([]);
  const [search, setSearch] = useState('');
  const [selectedCat, setSelectedCat] = useState(null);
  const [loading, setLoading] = useState(true);
  const [snack, setSnack] = useState('');
  // localQtys: { [productId]: qty } â€” quantity picker value before tapping "Add"
  const [localQtys, setLocalQtys] = useState({});

  const loadMenu = useCallback(async () => {
    setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (net.isConnected) {
        const data = await apiMenu();
        await saveCategories(data);
        setCategories(data);
      } else {
        const local = await getCategories();
        setCategories(local);
        const lastSynced = await getSyncMeta('menu_last_synced');
        if (lastSynced) {
          const age = Date.now() - new Date(lastSynced).getTime();
          if (age > MENU_STALE_THRESHOLD_MS) {
            setSnack('Menu may be outdated â€“ you are offline');
          }
        }
      }
    } catch {
      const local = await getCategories();
      setCategories(local);
      setSnack('Could not refresh menu');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMenu();
  }, [loadMenu]);

  // Categories that have at least one available product (used to filter chip bar)
  const catsWithProducts = useMemo(() => {
    const ids = new Set();
    categories.forEach((cat) => {
      (cat.subcategories || []).forEach((sub) => {
        if ((sub.products || []).some((p) => p.is_available !== false)) ids.add(cat.id);
      });
    });
    return ids;
  }, [categories]);

  // Build SectionList sections from categories -> subcategories -> products
  // Each section = one subcategory; section header shows category name when it’s
  // the first subcategory in its category.
  const sections = useMemo(() => {
    const q = search.trim().toLowerCase();
    const cats = selectedCat
      ? categories.filter((c) => c.id === selectedCat)
      : categories;

    const result = [];
    cats.forEach((cat) => {
      (cat.subcategories || []).forEach((sub, subIdx) => {
        let products = (sub.products || []).filter((p) => p.is_available !== false);
        if (q) {
          products = products.filter(
            (p) =>
              p.name.toLowerCase().includes(q) ||
              (p.description || '').toLowerCase().includes(q),
          );
        }
        if (products.length === 0) return;
        result.push({
          key: `${cat.id}-${sub.id}`,
          title: sub.name,
          categoryName: cat.name,
          catId: cat.id,
          isFirstInCategory: subIdx === 0,
          data: products,
        });
      });
    });
    return result;
  }, [categories, selectedCat, search]);

  const cartCount = getItemCount();
  const cartSubtotal = getSubtotal();

  const getCartQty = (productId) =>
    items.find((i) => i.product.id === productId)?.quantity || 0;

  const getLocalQty = (productId) => localQtys[productId] ?? 1;

  const setLocalQty = (productId, qty, maxStock) => {
    const clamped = Math.max(1, Math.min(qty, maxStock ?? 999));
    setLocalQtys((prev) => ({ ...prev, [productId]: clamped }));
  };

  const handleAddToCart = (product) => {
    const qty = getLocalQty(product.id);
    addItem(product, qty);
    // Reset qty back to 1 and show toast â€” matches web behaviour
    setLocalQtys((prev) => ({ ...prev, [product.id]: 1 }));
    setSnack(`${product.name} added to cart`);
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (!loading && sections.length === 0) {
    return (
      <View style={styles.container}>
        {/* Search + filter chips still visible */}
        <Searchbar
          placeholder="Search menu..."
          value={search}
          onChangeText={setSearch}
          style={styles.searchbar}
        />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.catList}>
          <Chip selected={!selectedCat} onPress={() => setSelectedCat(null)} style={styles.catChip}>All</Chip>
          {categories.filter((c) => catsWithProducts.has(c.id)).map((c) => (
            <Chip key={c.id} selected={selectedCat === c.id} onPress={() => setSelectedCat(selectedCat === c.id ? null : c.id)} style={styles.catChip}>{c.name}</Chip>
          ))}
        </ScrollView>
        <View style={styles.center}>
          <Text variant="bodyLarge" style={{ opacity: 0.5, fontFamily: 'Poppins_400Regular' }}>No items found</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Search bar */}
      <Searchbar
        placeholder="Search menu..."
        value={search}
        onChangeText={setSearch}
        style={styles.searchbar}
      />

      {/* Category filter chips - fixed height wrapper prevents chips stretching */}
      <View style={styles.catBar}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.catList}
        >
          <Chip
            selected={!selectedCat}
            onPress={() => setSelectedCat(null)}
            style={styles.catChip}
          >
            All
          </Chip>
          {categories.filter((cat) => catsWithProducts.has(cat.id)).map((cat) => (
            <Chip
              key={cat.id}
              selected={selectedCat === cat.id}
              onPress={() => setSelectedCat(selectedCat === cat.id ? null : cat.id)}
              style={styles.catChip}
            >
              {cat.name}
            </Chip>
          ))}
        </ScrollView>
      </View>

      <Divider />

      {/* Products â€” Category (h3) â†’ Subcategory (h5) â†’ Product cards */}
      <SectionList
        sections={sections}
        keyExtractor={(p) => String(p.id)}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={[
          styles.listContent,
          cartCount > 0 && styles.listContentWithBar,
        ]}
        renderSectionHeader={({ section }) => (
          <View>
            {/* Category header (h3 equivalent) â€” shown only for first subcategory */}
            {section.isFirstInCategory && (
              <View style={[styles.categoryHeader, { borderBottomColor: theme.colors.primary }]}>
                <Text variant="titleLarge" style={[styles.categoryHeaderText, { color: theme.colors.onBackground }]}>
                  {section.categoryName}
                </Text>
              </View>
            )}
            {/* Subcategory header (h5 equivalent) */}
            <Text
              variant="titleSmall"
              style={[styles.subcategoryHeader, { color: theme.colors.secondary }]}
            >
              {section.title}
            </Text>
          </View>
        )}
        renderItem={({ item: product }) => {
          const outOfStock = product.available_in_stock === 0;
          const localQty = getLocalQty(product.id);
          const cartQty = getCartQty(product.id);

          return (
            <Surface style={styles.productCard} elevation={1}>
              {/* Product image — only rendered when URL is present */}
              {!!product.image_url && (
                <Image source={{ uri: product.image_url }} style={styles.productImage} />
              )}

              <View style={styles.productBody}>
                {/* Name + promo badge row */}
                <View style={styles.nameBadgeRow}>
                  <Text variant="titleSmall" style={styles.productName} numberOfLines={1}>
                    {product.name}
                  </Text>
                  {product.has_promotion && (
                    <Chip compact mode="flat" style={styles.promoBadge} textStyle={styles.promoBadgeText}>
                      Happy Hour
                    </Chip>
                  )}
                  {cartQty > 0 && (
                    <Badge size={18} style={[styles.cartBadge, { backgroundColor: theme.colors.primary }]}>
                      {cartQty}
                    </Badge>
                  )}
                </View>

                {/* Description */}
                {product.description ? (
                  <Text variant="bodySmall" numberOfLines={2} style={styles.desc}>
                    {product.description}
                  </Text>
                ) : null}

                {/* Price row */}
                <View style={styles.priceRow}>
                  {product.has_promotion ? (
                    <>
                      <Text style={styles.origPrice}>
                        {format(product.original_price)}
                      </Text>
                      <Text variant="titleSmall" style={styles.salePrice}>
                        {format(product.current_price)}
                      </Text>
                    </>
                  ) : (
                    <Text variant="titleSmall" style={{ color: theme.colors.primary, fontFamily: 'Poppins_700Bold' }}>
                      {format(product.current_price)}
                    </Text>
                  )}
                  <Text variant="bodySmall" style={styles.prepTime}>
                    â± {product.preparation_time || '?'} min
                  </Text>
                </View>

                {/* Stock label */}
                {product.available_in_stock != null && (
                  <Text
                    variant="bodySmall"
                    style={[
                      styles.stockLabel,
                      { color: outOfStock ? theme.colors.error : '#2e7d32' },
                    ]}
                  >
                    {outOfStock
                      ? 'âœ— Out of Stock'
                      : `âœ“ ${product.available_in_stock} in stock`}
                  </Text>
                )}

                {/* Add row: qty control + Add button OR Out of Stock */}
                {outOfStock ? (
                  <Button
                    mode="outlined"
                    disabled
                    compact
                    style={styles.outOfStockBtn}
                  >
                    Out of Stock
                  </Button>
                ) : (
                  <View style={styles.addRow}>
                    <View style={styles.qtyControl}>
                      <IconButton
                        icon="minus"
                        size={16}
                        mode="contained-tonal"
                        style={styles.qtyBtn}
                        onPress={() =>
                          setLocalQty(product.id, localQty - 1, product.available_in_stock)
                        }
                      />
                      <Text variant="titleSmall" style={styles.qtyNum}>
                        {localQty}
                      </Text>
                      <IconButton
                        icon="plus"
                        size={16}
                        mode="contained-tonal"
                        style={styles.qtyBtn}
                        onPress={() =>
                          setLocalQty(product.id, localQty + 1, product.available_in_stock)
                        }
                      />
                    </View>
                    <Button
                      mode="contained"
                      compact
                      onPress={() => handleAddToCart(product)}
                      style={styles.addBtn}
                      icon="cart-plus"
                    >
                      Add
                    </Button>
                  </View>
                )}
              </View>
            </Surface>
          );
        }}
      />

      {/* Sticky bottom cart bar */}
      {cartCount > 0 && (
        <TouchableOpacity
          style={[styles.cartBar, { backgroundColor: theme.colors.primary }]}
          onPress={() => navigation.navigate('Cart')}
          activeOpacity={0.85}
        >
          <View style={styles.cartBarLeft}>
            <View style={[styles.cartCountBadge, { backgroundColor: theme.colors.primaryContainer }]}>
              <Text variant="labelSmall" style={{ color: theme.colors.primary, fontFamily: 'Poppins_700Bold' }}>
                {cartCount}
              </Text>
            </View>
            <Text variant="labelLarge" style={{ color: theme.colors.onPrimary, marginLeft: 8, fontFamily: 'Poppins_700Bold' }}>
              View Cart
            </Text>
          </View>
          <Text variant="titleSmall" style={{ color: theme.colors.onPrimary, fontFamily: 'Poppins_700Bold' }}>
            {format(cartSubtotal)}
          </Text>
        </TouchableOpacity>
      )}

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={2500}>
        {snack}
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  searchbar: { margin: 12, borderRadius: 12 },
  catBar: { height: 48, justifyContent: 'center' },
  catList: { paddingHorizontal: 12, alignItems: 'center' },
  catChip: { marginRight: 8 },

  listContent: { paddingBottom: 8 },
  listContentWithBar: { paddingBottom: 72 },

  // Category header â€” matches web's h3 with border-bottom
  categoryHeader: {
    marginTop: 20,
    marginHorizontal: 16,
    paddingBottom: 6,
    borderBottomWidth: 2,
    marginBottom: 8,
  },
  categoryHeaderText: { fontFamily: 'Poppins_700Bold' },

  // Subcategory header â€” matches web's h5 text-muted
  subcategoryHeader: {
    marginHorizontal: 16,
    marginTop: 8,
    marginBottom: 6,
    fontFamily: 'Poppins_600SemiBold',
    opacity: 0.75,
  },

  productCard: {
    flexDirection: 'row',
    marginHorizontal: 12,
    marginBottom: 10,
    borderRadius: 12,
    overflow: 'hidden',
  },
  productImage: { width: 100, height: 130 },
  productBody: { flex: 1, padding: 10 },

  nameBadgeRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 2 },
  productName: { flex: 1, fontFamily: 'Poppins_700Bold', marginRight: 4 },
  promoBadge: { backgroundColor: '#FFF3CD', marginRight: 4 },
  promoBadgeText: { fontSize: 10, color: '#856404' },
  cartBadge: { alignSelf: 'center' },

  desc: { opacity: 0.65, marginBottom: 4, fontSize: 12, fontFamily: 'Poppins_400Regular' },

  priceRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 2 },
  origPrice: { textDecorationLine: 'line-through', opacity: 0.5, fontSize: 13, fontFamily: 'Poppins_400Regular' },
  salePrice: { color: '#2e7d32', fontFamily: 'Poppins_700Bold' },
  prepTime: { marginLeft: 'auto', opacity: 0.6, fontFamily: 'Poppins_400Regular' },

  stockLabel: { fontSize: 11, marginBottom: 6, fontFamily: 'Poppins_400Regular' },

  addRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4 },
  qtyControl: { flexDirection: 'row', alignItems: 'center' },
  qtyBtn: { margin: 0, width: 28, height: 28 },
  qtyNum: { minWidth: 24, textAlign: 'center', fontFamily: 'Poppins_700Bold' },
  addBtn: { borderRadius: 20, flex: 1 },
  outOfStockBtn: { alignSelf: 'flex-start', marginTop: 4 },

  cartBar: {
    position: 'absolute',
    bottom: 0, left: 0, right: 0,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 14,
    elevation: 8,
  },
  cartBarLeft: { flexDirection: 'row', alignItems: 'center' },
  cartCountBadge: {
    width: 24, height: 24, borderRadius: 12,
    justifyContent: 'center', alignItems: 'center',
  },
});
