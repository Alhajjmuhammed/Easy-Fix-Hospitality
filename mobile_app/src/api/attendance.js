import client from './client';

export const apiAttendanceScan = (qrToken) =>
  client.post('/api/v1/attendance/scan/', { qr_token: qrToken }).then((r) => r.data);

export const apiAttendanceConfirm = (qrToken, action) =>
  client.post('/api/v1/attendance/confirm/', { qr_token: qrToken, action }).then((r) => r.data);

export const apiAttendanceMy = (page = 1, from = null, to = null) => {
  const params = { page };
  if (from) params.from = from;
  if (to)   params.to   = to;
  return client.get('/api/v1/attendance/my/', { params }).then((r) => r.data);
};

export const apiAttendanceStatus = () =>
  client.get('/api/v1/attendance/status/').then((r) => r.data);
