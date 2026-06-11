/**
 * feed-generator.ts — RSS 2.0 + JSON Feed 1.1 builder for the grade-change feed (E-34).
 */
import { SITE_NAME, SITE_URL } from './seo-defaults';

export interface GradeChange {
  id: string;
  protocol_slug: string;
  protocol_name: string;
  detected_at: string;
  from_grade: string;
  to_grade: string;
  rubric_version: string;
  snapshot_date_before: string;
  snapshot_date_after: string;
  reason?: string | null;
  is_upgrade: boolean;
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function changeTitle(ch: GradeChange): string {
  const dir = ch.is_upgrade ? '↑' : '↓';
  return `${dir} ${ch.protocol_name}: ${ch.from_grade}→${ch.to_grade}`;
}

function changeDescription(ch: GradeChange): string {
  const dir = ch.is_upgrade ? 'Upgraded' : 'Downgraded';
  return `${ch.protocol_name} ${dir} from Grade ${ch.from_grade} to Grade ${ch.to_grade}${ch.reason ? `. ${ch.reason}` : ''}`;
}

function changeUrl(ch: GradeChange): string {
  return `${SITE_URL}/changes/${ch.id}/`;
}

/** Generate RSS 2.0 XML for the grade-change feed. */
export function buildRssFeed(changes: GradeChange[]): string {
  const lastBuildDate = changes.length > 0
    ? new Date(changes[0].detected_at).toUTCString()
    : new Date().toUTCString();

  const items = changes.map((ch) => `
    <item>
      <title>${escapeXml(changeTitle(ch))}</title>
      <link>${escapeXml(changeUrl(ch))}</link>
      <guid isPermaLink="true">${escapeXml(changeUrl(ch))}</guid>
      <description>${escapeXml(changeDescription(ch))}</description>
      <pubDate>${new Date(ch.detected_at).toUTCString()}</pubDate>
      <category>${escapeXml(ch.is_upgrade ? 'upgrade' : 'downgrade')}</category>
    </item>`).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${escapeXml(SITE_NAME)} — Grade Changes</title>
    <link>${SITE_URL}/changes/</link>
    <description>Protocol risk grade upgrades and downgrades from DeFi Risk.</description>
    <language>en</language>
    <lastBuildDate>${lastBuildDate}</lastBuildDate>
    <atom:link href="${SITE_URL}/feeds/grade-changes.xml" rel="self" type="application/rss+xml" />
${items}
  </channel>
</rss>`;
}

/** Generate JSON Feed 1.1 for the grade-change feed. */
export function buildJsonFeed(changes: GradeChange[]): object {
  return {
    version: 'https://jsonfeed.org/version/1.1',
    title: `${SITE_NAME} — Grade Changes`,
    home_page_url: `${SITE_URL}/changes/`,
    feed_url: `${SITE_URL}/feeds/grade-changes.json`,
    description: 'Protocol risk grade upgrades and downgrades from DeFi Risk.',
    language: 'en',
    items: changes.map((ch) => ({
      id: changeUrl(ch),
      url: changeUrl(ch),
      title: changeTitle(ch),
      content_text: changeDescription(ch),
      date_published: ch.detected_at,
      tags: [ch.is_upgrade ? 'upgrade' : 'downgrade', ch.protocol_slug],
      _risk_dashboard: {
        protocol_slug: ch.protocol_slug,
        from_grade: ch.from_grade,
        to_grade: ch.to_grade,
        rubric_version: ch.rubric_version,
        snapshot_date_before: ch.snapshot_date_before,
        snapshot_date_after: ch.snapshot_date_after,
        is_upgrade: ch.is_upgrade,
      },
    })),
  };
}
