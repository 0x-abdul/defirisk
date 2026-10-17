import { getProtocol, listPublishedProtocolSlugs } from './data-loaders';
import { toComparisonProtocol, type ComparisonProtocol } from './protocol-comparison';

/** Same committed public detail records used by protocol pages; no private sources. */
export function listComparisonProtocols(): ComparisonProtocol[] {
  return listPublishedProtocolSlugs()
    .flatMap((slug) => {
      const detail = getProtocol(slug);
      const protocol = detail && toComparisonProtocol(slug, detail);
      return protocol ? [protocol] : [];
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}
