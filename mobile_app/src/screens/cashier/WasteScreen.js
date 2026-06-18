import React, { useEffect, useState } from 'react';
import { View, ScrollView, StyleSheet } from 'react-native';
import {
  Text, Card, Button, TextInput, ActivityIndicator,
  Snackbar, useTheme, Divider,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { apiMenu } from '../../api/menu';
import { apiRecordWaste } from '../../api/waste';

// ── Constants mirroring backend FoodWasteLog choices ───────────────────────
const WASTE_REASONS = [
  { value: 'customer_refused',    label: 'Customer Refused' },
  { value: 'customer_left',       label: 'Customer Left' },
  { value: 'wrong_order',         label: 'Wrong Order' },
  { value: 'quality_issue',       label: 'Quality Issue' },
  { value: 'kitchen_error',       label: 'Kitchen Error' },
  { value: 'overcooking',         label: 'Overcooked' },
  { value: 'undercooking',        label: 'Undercooked' },
  { value: 'contamination',       label: 'Contamination' },
  { value: 'equipment_failure',   label: 'Equipment Failure' },
  { value: 'ingredient_expired',  label: 'Expired Ingredients' },
  { value: 'staff_error',         label: 'Staff Error' },
  { value: 'customer_complaint',  label: 'Customer Complaint' },
  { value: 'other',               label: 'Other' },
];

const DISPOSAL_METHODS = [
  { value: 'waste_bin',          label: 'Waste Bin' },
  { value: 'staff_meal',         label: 'Staff Meal' },
  { value: 'compost',            label: 'Compost' },
  { value: 'donated',            label: 'Donated' },
  { value: 'returned_supplier',  label: 'Returned to Supplier' },
];

// ── Simple chip-style picker used for both reason and disposal ─────────────
function ChipPicker({ items, selected, onSelect }) {
  return (
    <View style={styles.chipGrid}>
      {items.map((item) => (
        <Button
          key={item.value}
          compact
          mode={selected === item.value ? 'contained' : 'outlined'}
          onPress={() => onSelect(item.value)}
          style={[styles.chip, selected === item.value && styles.chipSelected]}
          labelStyle={styles.chipLabel}
        >
          {item.label}
        </Button>
      ))}
    </View>
  );
}

export default function CashierWasteScreen() {
  const theme = useTheme();

  // Products loaded from menu API
  const [products,        setProducts]        = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [productSearch,   setProductSearch]   = useState('');
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [productMenuOpen, setProductMenuOpen] = useState(false);

  // Form fields
  const [quantity,        setQuantity]        = useState('1');
  const [wasteReason,     setWasteReason]     = useState('other');
  const [disposalMethod,  setDisposalMethod]  = useState('waste_bin');
  const [notes,           setNotes]           = useState('');

  // Submission state
  const [submitting, setSubmitting] = useState(false);
  const [snack,      setSnack]      = useState('');
  const [snackColor, setSnackColor] = useState('#323232');

  // ── Load products once ────────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const data = await apiMenu();
        // apiMenu returns { categories: [{products: [...]}, ...] }
        const flat = [];
        const categories = data || [];
        categories.forEach((cat) => {
          (cat.products || []).forEach((p) => flat.push(p));
        });
        setProducts(flat);
      } catch {
        setSnack('Could not load menu');
        setSnackColor('#E53935');
      } finally {
        setLoadingProducts(false);
      }
    })();
  }, []);

  const filteredProducts = products.filter((p) =>
    p.name.toLowerCase().includes(productSearch.toLowerCase())
  );

  // ── Submit ─────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (!selectedProduct) { setSnack('Please select a product'); setSnackColor('#E53935'); return; }
    const qty = parseInt(quantity, 10);
    if (!qty || qty <= 0) { setSnack('Enter a valid quantity'); setSnackColor('#E53935'); return; }

    setSubmitting(true);
    try {
      await apiRecordWaste({
        product_id:      selectedProduct.id,
        quantity_wasted: qty,
        waste_reason:    wasteReason,
        disposal_method: disposalMethod,
        notes:           notes.trim(),
      });
      setSnack('Waste record saved');
      setSnackColor('#2E7D32');
      // Reset form
      setSelectedProduct(null);
      setProductSearch('');
      setQuantity('1');
      setWasteReason('other');
      setDisposalMethod('waste_bin');
      setNotes('');
    } catch (err) {
      setSnack(err.response?.data?.error || 'Could not save waste record');
      setSnackColor('#E53935');
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingProducts) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">

      {/* ── Product Selector ─────────────────────────────────────────── */}
      <Card style={styles.card}>
        <Card.Title
          title="Product"
          left={() => <MaterialCommunityIcons name="food" size={22} color={theme.colors.primary} />}
        />
        <Card.Content>
          <TextInput
            label="Search product…"
            value={productSearch}
            onChangeText={(t) => { setProductSearch(t); setProductMenuOpen(true); setSelectedProduct(null); }}
            mode="outlined"
            left={<TextInput.Icon icon="magnify" />}
            style={{ marginBottom: 8 }}
            onFocus={() => setProductMenuOpen(true)}
          />
          {selectedProduct ? (
            <View style={styles.selectedRow}>
              <MaterialCommunityIcons name="check-circle" size={18} color="#2E7D32" />
              <Text variant="bodyMedium" style={{ marginLeft: 8, flex: 1, fontFamily: 'Poppins_600SemiBold' }}>
                {selectedProduct.name}
              </Text>
              <Button compact onPress={() => { setSelectedProduct(null); setProductSearch(''); }}>
                Change
              </Button>
            </View>
          ) : productMenuOpen && filteredProducts.length > 0 ? (
            <View style={styles.productList}>
              {filteredProducts.slice(0, 8).map((p) => (
                <Button
                  key={p.id}
                  mode="text"
                  onPress={() => { setSelectedProduct(p); setProductSearch(p.name); setProductMenuOpen(false); }}
                  style={styles.productRow}
                  contentStyle={{ justifyContent: 'flex-start' }}
                >
                  {p.name}
                </Button>
              ))}
            </View>
          ) : null}
        </Card.Content>
      </Card>

      {/* ── Quantity ──────────────────────────────────────────────────── */}
      <Card style={styles.card}>
        <Card.Title
          title="Quantity Wasted"
          left={() => <MaterialCommunityIcons name="counter" size={22} color={theme.colors.primary} />}
        />
        <Card.Content>
          <TextInput
            label="Quantity"
            value={quantity}
            onChangeText={setQuantity}
            keyboardType="number-pad"
            mode="outlined"
          />
        </Card.Content>
      </Card>

      {/* ── Waste Reason ─────────────────────────────────────────────── */}
      <Card style={styles.card}>
        <Card.Title
          title="Waste Reason"
          left={() => <MaterialCommunityIcons name="alert-circle-outline" size={22} color={theme.colors.primary} />}
        />
        <Card.Content>
          <ChipPicker items={WASTE_REASONS} selected={wasteReason} onSelect={setWasteReason} />
        </Card.Content>
      </Card>

      {/* ── Disposal Method ──────────────────────────────────────────── */}
      <Card style={styles.card}>
        <Card.Title
          title="Disposal Method"
          left={() => <MaterialCommunityIcons name="trash-can-outline" size={22} color={theme.colors.primary} />}
        />
        <Card.Content>
          <ChipPicker items={DISPOSAL_METHODS} selected={disposalMethod} onSelect={setDisposalMethod} />
        </Card.Content>
      </Card>

      {/* ── Notes ─────────────────────────────────────────────────────── */}
      <Card style={styles.card}>
        <Card.Title
          title="Notes (optional)"
          left={() => <MaterialCommunityIcons name="note-text-outline" size={22} color={theme.colors.primary} />}
        />
        <Card.Content>
          <TextInput
            label="Additional notes…"
            value={notes}
            onChangeText={setNotes}
            mode="outlined"
            multiline
            numberOfLines={3}
          />
        </Card.Content>
      </Card>

      <Divider style={{ marginVertical: 8 }} />

      <Button
        mode="contained"
        icon="check"
        onPress={handleSubmit}
        loading={submitting}
        disabled={submitting}
        style={styles.submitBtn}
        contentStyle={{ paddingVertical: 6 }}
      >
        Record Waste
      </Button>

      <Snackbar
        visible={!!snack}
        onDismiss={() => setSnack('')}
        duration={3000}
        style={{ backgroundColor: snackColor }}
      >
        {snack}
      </Snackbar>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container:   { flex: 1, backgroundColor: '#F5F5F5' },
  content:     { padding: 12, paddingBottom: 32 },
  center:      { flex: 1, justifyContent: 'center', alignItems: 'center' },
  card:        { marginBottom: 12, borderRadius: 10 },
  selectedRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#E8F5E9', padding: 10, borderRadius: 8 },
  productList: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, overflow: 'hidden' },
  productRow:  { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee' },
  chipGrid:    { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip:        { borderRadius: 20, marginBottom: 2 },
  chipSelected: {},
  chipLabel:   { fontSize: 11 },
  submitBtn:   { marginTop: 8, borderRadius: 10 },
});
