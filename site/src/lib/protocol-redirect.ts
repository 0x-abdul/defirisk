export function buildProtocolFamilyRedirect(
  canonicalFamily: string,
  search: string,
  selectedSurface?: string
): string {
  const params = new URLSearchParams(search);
  if (selectedSurface) params.set('surface', selectedSurface);

  const query = params.toString();
  return `/protocols/${canonicalFamily}/${query ? `?${query}` : ''}`;
}
