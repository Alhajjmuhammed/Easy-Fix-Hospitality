import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  View, FlatList, StyleSheet, RefreshControl,
} from 'react-native';
import {
  Text, Card, Chip, ActivityIndicator, Divider, Button, useTheme,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { apiAttendanceMy, apiAttendanceStatus } from '../../api/attendance';

// ─── Helpers ──────────────────────────────────────────────────────────────────
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function fmtTime(str) {
  if (!str) return '—';
  const parts = str.split(':');
  const h = parseInt(parts[0], 10);
  const m = parts[1] || '00';
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m} ${ampm}`;
}

function fmtDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

// ─── Today status card ────────────────────────────────────────────────────────
function TodayStatusCard({ status, loading }) {
  if (loading) {
    return (
      <Card style={styles.todayCard}>
        <Card.Content style={styles.center}>
          <ActivityIndicator size="small" />
        </Card.Content>
      </Card>
    );
  }
  if (!status) return null;

  const { checked_in, checked_out, record } = status;
  const statusText = checked_out
    ? 'Completed for today'
    : checked_in
    ? 'Checked In — not yet checked out'
    : 'Not yet checked in today';
  const statusColor = checked_out ? '#2E7D32' : checked_in ? '#E65100' : '#9E9E9E';
  const iconName = checked_out ? 'check-circle' : checked_in ? 'login' : 'clock-alert-outline';

  return (
    <Card style={[styles.todayCard, { borderLeftColor: statusColor, borderLeftWidth: 4 }]}>
      <Card.Content>
        <View style={styles.todayHeader}>
          <MaterialCommunityIcons name={iconName} size={22} color={statusColor} />
          <Text style={[styles.todayTitle, { color: statusColor }]}>Today's Status</Text>
        </View>
        <Text style={styles.todayStatus}>{statusText}</Text>
        {record ? (
          <View style={styles.todayTimes}>
            {record.check_in ? (
              <View style={styles.timeChip}>
                <MaterialCommunityIcons name="login" size={14} color="#1565C0" />
                <Text style={styles.timeChipText}>{fmtTime(record.check_in)}</Text>
              </View>
            ) : null}
            {record.check_out ? (
              <View style={styles.timeChip}>
                <MaterialCommunityIcons name="logout" size={14} color="#2E7D32" />
                <Text style={styles.timeChipText}>{fmtTime(record.check_out)}</Text>
              </View>
            ) : null}
            {record.work_hours_display ? (
              <View style={styles.timeChip}>
                <MaterialCommunityIcons name="timer-outline" size={14} color="#6A1B9A" />
                <Text style={styles.timeChipText}>{record.work_hours_display}</Text>
              </View>
            ) : null}
          </View>
        ) : null}
      </Card.Content>
    </Card>
  );
}

// ─── Summary row ─────────────────────────────────────────────────────────────
function SummaryRow({ records }) {
  const totalDays   = records.length;
  const lateCount   = records.filter((r) => r.is_late).length;
  const overtimeCount = records.filter((r) => r.is_overtime).length;

  return (
    <View style={styles.summaryRow}>
      <View style={styles.summaryItem}>
        <Text style={styles.summaryNumber}>{totalDays}</Text>
        <Text style={styles.summaryLabel}>Days</Text>
      </View>
      <View style={styles.summaryDivider} />
      <View style={styles.summaryItem}>
        <Text style={[styles.summaryNumber, lateCount > 0 && { color: '#E53935' }]}>
          {lateCount}
        </Text>
        <Text style={styles.summaryLabel}>Late</Text>
      </View>
      <View style={styles.summaryDivider} />
      <View style={styles.summaryItem}>
        <Text style={[styles.summaryNumber, overtimeCount > 0 && { color: '#6A1B9A' }]}>
          {overtimeCount}
        </Text>
        <Text style={styles.summaryLabel}>Overtime</Text>
      </View>
    </View>
  );
}

// ─── Record row ───────────────────────────────────────────────────────────────
function RecordRow({ item }) {
  return (
    <View style={styles.recordRow}>
      {/* Date + Shift */}
      <View style={styles.recordLeft}>
        <Text style={styles.recordDate}>{fmtDate(item.date)}</Text>
        {item.shift_name ? (
          <Text style={styles.recordShift}>{item.shift_name}</Text>
        ) : null}
      </View>

      {/* Times */}
      <View style={styles.recordMiddle}>
        <View style={styles.recordTimeRow}>
          <MaterialCommunityIcons name="login" size={13} color="#1565C0" />
          <Text style={styles.recordTime}>{fmtTime(item.check_in)}</Text>
        </View>
        <View style={styles.recordTimeRow}>
          <MaterialCommunityIcons name="logout" size={13} color="#2E7D32" />
          <Text style={styles.recordTime}>{fmtTime(item.check_out)}</Text>
        </View>
      </View>

      {/* Hours + badges */}
      <View style={styles.recordRight}>
        <Text style={styles.recordHours}>{item.work_hours_display || '—'}</Text>
        <View style={styles.badgeRow}>
          {item.is_late ? (
            <View style={styles.badgeLate}>
              <Text style={styles.badgeText}>
                Late{item.late_minutes ? ` ${item.late_minutes}m` : ''}
              </Text>
            </View>
          ) : null}
          {item.is_overtime ? (
            <View style={styles.badgeOvertime}>
              <Text style={styles.badgeText}>
                OT{item.overtime_minutes ? ` ${item.overtime_minutes}m` : ''}
              </Text>
            </View>
          ) : null}
        </View>
      </View>
    </View>
  );
}

// ─── Main screen ─────────────────────────────────────────────────────────────
export default function MyAttendanceScreen() {
  const theme = useTheme();
  const mountedRef = useRef(true);

  const now = new Date();
  const [year,  setYear]  = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1); // 1-based

  const [records,      setRecords]      = useState([]);
  const [loading,      setLoading]      = useState(false);
  const [refreshing,   setRefreshing]   = useState(false);
  const [page,         setPage]         = useState(1);
  const [totalPages,   setTotalPages]   = useState(1);

  const [todayStatus,        setTodayStatus]        = useState(null);
  const [todayStatusLoading, setTodayStatusLoading] = useState(false);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  // ── Fetch today status once on mount ────────────────────────────────────────
  useEffect(() => {
    (async () => {
      if (!mountedRef.current) return;
      setTodayStatusLoading(true);
      try {
        const data = await apiAttendanceStatus();
        if (mountedRef.current) setTodayStatus(data);
      } catch {
        // Silently ignore — card just won't show
      } finally {
        if (mountedRef.current) setTodayStatusLoading(false);
      }
    })();
  }, []);

  // ── Fetch records when month/year/page changes ───────────────────────────────
  const fetchRecords = useCallback(async (pg = 1, isRefresh = false) => {
    if (!mountedRef.current) return;
    if (isRefresh) setRefreshing(true);
    else           setLoading(true);

    try {
      // The API accepts page; filter by year+month if supported, else client-side
      const data = await apiAttendanceMy(pg);
      if (!mountedRef.current) return;

      // Filter by selected year + month (works whether server filters or not)
      const filtered = (data.results || []).filter((r) => {
        if (!r.date) return false;
        const d = new Date(r.date);
        return d.getFullYear() === year && d.getMonth() + 1 === month;
      });

      setRecords(filtered);
      setPage(data.page || pg);
      setTotalPages(data.num_pages || 1);
    } catch {
      if (mountedRef.current) {
        setRecords([]);
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [year, month]);

  useEffect(() => {
    fetchRecords(1);
  }, [fetchRecords]);

  // ── Month navigation ─────────────────────────────────────────────────────────
  const prevMonth = () => {
    if (month === 1) { setYear((y) => y - 1); setMonth(12); }
    else             { setMonth((m) => m - 1); }
  };

  const nextMonth = () => {
    const today = new Date();
    if (year > today.getFullYear() || (year === today.getFullYear() && month >= today.getMonth() + 1)) return;
    if (month === 12) { setYear((y) => y + 1); setMonth(1); }
    else              { setMonth((m) => m + 1); }
  };

  const isCurrentMonth = () => {
    const today = new Date();
    return year === today.getFullYear() && month === today.getMonth() + 1;
  };

  // ── List header ──────────────────────────────────────────────────────────────
  const ListHeader = () => (
    <View>
      {/* Today's status */}
      <TodayStatusCard status={todayStatus} loading={todayStatusLoading} />

      {/* Month selector */}
      <Card style={styles.monthCard}>
        <Card.Content style={styles.monthRow}>
          <Button
            compact
            mode="text"
            icon="chevron-left"
            onPress={prevMonth}
            labelStyle={{ fontFamily: 'Poppins_600SemiBold' }}
          >
            {''}
          </Button>
          <Text style={styles.monthLabel}>
            {MONTHS[month - 1]} {year}
          </Text>
          <Button
            compact
            mode="text"
            icon="chevron-right"
            onPress={nextMonth}
            disabled={isCurrentMonth()}
            labelStyle={{ fontFamily: 'Poppins_600SemiBold' }}
          >
            {''}
          </Button>
        </Card.Content>
      </Card>

      {/* Summary */}
      {records.length > 0 && (
        <Card style={styles.summaryCard}>
          <Card.Content>
            <SummaryRow records={records} />
          </Card.Content>
        </Card>
      )}

      {/* Table header */}
      {records.length > 0 && (
        <View style={styles.tableHeader}>
          <Text style={[styles.tableHeaderCell, { flex: 1.4 }]}>Date</Text>
          <Text style={[styles.tableHeaderCell, { flex: 1.2 }]}>In / Out</Text>
          <Text style={[styles.tableHeaderCell, { flex: 1, textAlign: 'right' }]}>Hours</Text>
        </View>
      )}
    </View>
  );

  // ── Empty state ──────────────────────────────────────────────────────────────
  const ListEmpty = () => (
    <View style={styles.emptyContainer}>
      <MaterialCommunityIcons name="calendar-blank-outline" size={56} color="#B0BEC5" />
      <Text style={styles.emptyTitle}>No records for {MONTHS[month - 1]}</Text>
      <Text style={styles.emptyBody}>Your attendance for this month will appear here.</Text>
    </View>
  );

  // ── List footer (pagination) ──────────────────────────────────────────────────
  const ListFooter = () => {
    if (totalPages <= 1) return null;
    return (
      <View style={styles.pagination}>
        <Button
          compact
          mode="outlined"
          disabled={page <= 1 || loading}
          onPress={() => fetchRecords(page - 1)}
          icon="chevron-left"
        >
          Prev
        </Button>
        <Text style={styles.pageText}>Page {page} / {totalPages}</Text>
        <Button
          compact
          mode="outlined"
          disabled={page >= totalPages || loading}
          onPress={() => fetchRecords(page + 1)}
          icon="chevron-right"
          contentStyle={{ flexDirection: 'row-reverse' }}
        >
          Next
        </Button>
      </View>
    );
  };

  return (
    <View style={styles.container}>
      {loading && records.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={theme.colors.primary} />
        </View>
      ) : (
        <FlatList
          data={records}
          keyExtractor={(item) => String(item.id)}
          renderItem={({ item, index }) => (
            <View>
              <RecordRow item={item} />
              {index < records.length - 1 && <Divider />}
            </View>
          )}
          ListHeaderComponent={<ListHeader />}
          ListEmptyComponent={<ListEmpty />}
          ListFooterComponent={<ListFooter />}
          contentContainerStyle={styles.listContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => fetchRecords(1, true)}
              colors={[theme.colors.primary]}
            />
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container:  { flex: 1, backgroundColor: '#F5F5F5' },
  center:     { flex: 1, justifyContent: 'center', alignItems: 'center' },
  listContent: { padding: 12, paddingBottom: 32 },

  // Today card
  todayCard: {
    marginBottom: 10,
    borderRadius: 10,
  },
  todayHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  todayTitle: {
    fontFamily: 'Poppins_700Bold',
    fontSize: 15,
  },
  todayStatus: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 13,
    color: '#555',
    marginBottom: 8,
  },
  todayTimes: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  timeChip: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#EEF2F7',
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 4,
    gap: 4,
  },
  timeChipText: {
    fontFamily: 'Poppins_600SemiBold',
    fontSize: 12,
    color: '#333',
  },

  // Month selector
  monthCard: { marginBottom: 10, borderRadius: 10 },
  monthRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  monthLabel: {
    fontFamily: 'Poppins_700Bold',
    fontSize: 16,
    color: '#2c3e50',
  },

  // Summary
  summaryCard: { marginBottom: 10, borderRadius: 10 },
  summaryRow:  { flexDirection: 'row', justifyContent: 'space-around', alignItems: 'center' },
  summaryItem: { alignItems: 'center', flex: 1 },
  summaryNumber: {
    fontFamily: 'Poppins_700Bold',
    fontSize: 24,
    color: '#2c3e50',
  },
  summaryLabel: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 12,
    color: '#888',
    marginTop: 2,
  },
  summaryDivider: {
    width: 1,
    height: 36,
    backgroundColor: '#E0E0E0',
  },

  // Table header
  tableHeader: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: '#ECEFF1',
    borderRadius: 6,
    marginBottom: 4,
  },
  tableHeaderCell: {
    fontFamily: 'Poppins_600SemiBold',
    fontSize: 11,
    color: '#607D8B',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },

  // Record row
  recordRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    paddingHorizontal: 12,
    paddingVertical: 12,
    gap: 8,
  },
  recordLeft: {
    flex: 1.4,
  },
  recordDate: {
    fontFamily: 'Poppins_600SemiBold',
    fontSize: 13,
    color: '#2c3e50',
  },
  recordShift: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 11,
    color: '#888',
    marginTop: 1,
  },
  recordMiddle: {
    flex: 1.2,
    gap: 4,
  },
  recordTimeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  recordTime: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 12,
    color: '#444',
  },
  recordRight: {
    flex: 1,
    alignItems: 'flex-end',
    gap: 4,
  },
  recordHours: {
    fontFamily: 'Poppins_700Bold',
    fontSize: 13,
    color: '#2c3e50',
  },
  badgeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    justifyContent: 'flex-end',
  },
  badgeLate: {
    backgroundColor: '#FFEBEE',
    borderRadius: 10,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  badgeOvertime: {
    backgroundColor: '#EDE7F6',
    borderRadius: 10,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  badgeText: {
    fontFamily: 'Poppins_700Bold',
    fontSize: 10,
    color: '#333',
  },

  // Empty state
  emptyContainer: {
    alignItems: 'center',
    paddingTop: 48,
    paddingHorizontal: 32,
    gap: 12,
  },
  emptyTitle: {
    fontFamily: 'Poppins_700Bold',
    fontSize: 16,
    color: '#90A4AE',
    textAlign: 'center',
  },
  emptyBody: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 13,
    color: '#B0BEC5',
    textAlign: 'center',
    lineHeight: 20,
  },

  // Pagination
  pagination: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
    paddingTop: 16,
  },
  pageText: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 13,
    color: '#666',
  },
});
