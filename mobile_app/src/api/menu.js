import client from './client';

export const apiMenu = (since = null) =>
  client.get('/menu/', { params: since ? { since } : {} }).then((r) => r.data.categories);

export const apiMenuChanges = (since) =>
  client.get('/menu/changes/', { params: { since } }).then((r) => r.data.products);
