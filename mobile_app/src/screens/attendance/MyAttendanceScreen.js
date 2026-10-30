import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  View, FlatList, StyleSheet, RefreshControl,
} from 'react-native';
import {
  Text, Card, Chip, ActivityIndicator, Divider, Button, useTheme,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { apiAttendanceMy, apiAttendanceStatus, apiMyRoster } from '../../api/attendance';
import { useT } from '../../i18n';

// ─── Helpers ──────────────────────────────────────────────────────────────────
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function fmtTime(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return '—';
  const h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, '0');
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
  const t = useT();
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
          <Text style={[styles.todayTitle, { color: statusColor }]}>{t("Today's Status")}</Text>
        </View>
        <Text style={styles.todayStatus}>{t(statusText)}</Text>
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

// ─── Upcoming shifts (published roster) ──────────────────────────────────────
function localIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function fmtRosterDate(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

function UpcomingShiftsCard({ entries }) {
  const t = useT();
  if (!entries || entries.length === 0) return null;
  const today = localIso(new Date());
  return (
    <Card style={styles.todayCard}>
      <Card.Content>
        <View style={styles.todayHeader}>
          <MaterialCommunityIcons name="calendar-week" size={22} color="#1565C0" />
          <Text style={[styles.todayTitle, { color: '#1565C0' }]}>{t('My Upcoming Shifts')}</Text>
        </View>
        {entries.map((e) => (
          <View key={e.date} style={[styles.shiftRow, e.date === today && styles.shiftRowToday]}>
            <Text style={styles.shiftDate}>{e.date === today ? t('Today') : fmtRosterDate(e.date)}</Text>
            {e.kind === 'shift' ? (
              <Text style={styles.shiftTime}>
                {e.start_time ? `${e.start_time}–${e.end_time}` : t('Shift to be confirmed')}
                {e.shift_name ? <Text style={styles.shiftName}>  {e.shift_name}</Text> : null}
              </Text>
            ) : (
              <Text style={[styles.shiftTime, { color: e.kind === 'leave' ? '#E65100' : '#888' }]}>{e.kind_display}</Text>
            )}
          </View>
        ))}
      </Card.Content>
    </Card>
  );
}

// ─── Summary row ─────────────────────────────────────────────────────────────
function SummaryRow({ records }) {
  const t = useT();
  const totalDays   = records.length;
  const lateCount   = records.filter((r) => r.is_late).length;
  const overtimeCount = records.filter((r) => r.is_overtime).length;

  return (
    <View style={styles.summaryRow}>
      <View style={styles.summaryItem}>
        <Text style={styles.summaryNumber}>{totalDays}</Text>
        <Text style={styles.summaryLabel}>{t('Days')}</Text>
      </View>
      <View style={styles.summaryDivider} />
      <View style={styles.summaryItem}>
        <Text style={[styles.summaryNumber, lateCount > 0 && { color: '#E53935' }]}>
          {lateCount}
        </Text>
        <Text style={styles.summaryLabel}>{t('Late')}</Text>
      </View>
      <View style={styles.summaryDivider} />
      <View style={styles.summaryItem}>
        <Text style={[styles.summaryNumber, overtimeCount > 0 && { color: '#6A1B9A' }]}>
          {overtimeCount}
        </Text>
        <Text style={styles.summaryLabel}>{t('Overtime')}</Text>
      </View>
    </View>
  );
}

// ─── Record row ───────────────────────────────────────────────────────────────
function RecordRow({ item }) {
  const t = useT();
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
                {t('Late')}{item.late_minutes ? ` ${item.late_minutes}m` : ''}
              </Text>
            </View>
          ) : null}
          {item.is_overtime ? (
            <View style={styles.badgeOvertime}>
              <Text style={styles.badgeText}>
                {t('OT')}{item.overtime_minutes ? ` ${item.overtime_minutes}m` : ''}
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
  const t = useT();
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
  const [roster,             setRoster]             = useState([]);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  // ── Upcoming shifts (older servers without the roster just return 404 → hidden) ──
  const fetchRoster = useCallback(async () => {
    try {
      const data = await apiMyRoster();
      if (mountedRef.current) setRoster(data.entries || []);
    } catch {
      // Card just won't show
    }
  }, []);

  // Refetch whenever the screen comes into view (e.g. opened again from a roster notification)
  useFocusEffect(useCallback(() => { fetchRoster(); }, [fetchRoster]));

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
      // Pass date range so server returns only the selected month's records
      const daysInMonth = new Date(year, month, 0).getDate();
      const from = `${year}-${String(month).padStart(2, '0')}-01`;
      const to   = `${year}-${String(month).padStart(2, '0')}-${String(daysInMonth).padStart(2, '0')}`;
      const data = await apiAttendanceMy(pg, from, to);
      if (!mountedRef.current) return;

      setRecords(data.results || []);
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

      {/* Planned shifts */}
      <UpcomingShiftsCard entries={roster} />

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
            {t(MONTHS[month - 1])} {year}
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
          <Text style={[styles.tableHeaderCell, { flex: 1.4 }]}>{t('Date')}</Text>
          <Text style={[styles.tableHeaderCell, { flex: 1.2 }]}>{t('In / Out')}</Text>
          <Text style={[styles.tableHeaderCell, { flex: 1, textAlign: 'right' }]}>{t('Hours')}</Text>
        </View>
      )}
    </View>
  );

  // ── Empty state ──────────────────────────────────────────────────────────────
  const ListEmpty = () => (
    <View style={styles.emptyContainer}>
      <MaterialCommunityIcons name="calendar-blank-outline" size={56} color="#B0BEC5" />
      <Text style={styles.emptyTitle}>{t('No records for {month}', { month: t(MONTHS[month - 1]) })}</Text>
      <Text style={styles.emptyBody}>{t('Your attendance for this month will appear here.')}</Text>
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
          {t('Prev')}
        </Button>
        <Text style={styles.pageText}>{t('Page {page} / {total}', { page, total: totalPages })}</Text>
        <Button
          compact
          mode="outlined"
          disabled={page >= totalPages || loading}
          onPress={() => fetchRecords(page + 1)}
          icon="chevron-right"
          contentStyle={{ flexDirection: 'row-reverse' }}
        >
          {t('Next')}
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
              onRefresh={() => { fetchRoster(); fetchRecords(1, true); }}
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

  // Upcoming shifts
  shiftRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 6,
    paddingHorizontal: 6,
    borderRadius: 6,
    gap: 10,
  },
  shiftRowToday: { backgroundColor: '#E3F2FD' },
  shiftDate: { fontFamily: 'Poppins_600SemiBold', fontSize: 13, color: '#2c3e50', width: 96 },
  shiftTime: { fontFamily: 'Poppins_600SemiBold', fontSize: 13, color: '#2E7D32', flex: 1 },
  shiftName: { fontFamily: 'Poppins_400Regular', fontSize: 12, color: '#888' },

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
