import client from './client';

export const apiAttendanceScan = (qrToken) =>
  client.post('/attendance/scan/', { qr_token: qrToken }).then((r) => r.data);

export const apiAttendanceConfirm = (qrToken, action) =>
  client.post('/attendance/confirm/', { qr_token: qrToken, action }).then((r) => r.data);

export const apiAttendanceMy = (page = 1, from = null, to = null) => {
  const params = { page };
  if (from) params.from = from;
  if (to)   params.to   = to;
  return client.get('/attendance/my/', { params }).then((r) => r.data);
};

export const apiMyRoster = () =>
  client.get('/attendance/roster/my/').then((r) => r.data);

export const apiAttendanceStatus = () =>
  client.get('/attendance/status/').then((r) => r.data);
