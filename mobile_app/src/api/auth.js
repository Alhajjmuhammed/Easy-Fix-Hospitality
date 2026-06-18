import client from './client';

export const apiLogin = (username, password) =>
  client.post('/auth/login/', { username, password });

export const apiLogout = () => client.post('/auth/logout/');

export const apiMe = () => client.get('/auth/me/');

export const apiRegister = (data) =>
  client.post('/auth/register/', data);
