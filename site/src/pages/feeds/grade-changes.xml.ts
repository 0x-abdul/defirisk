import type { APIRoute } from 'astro';
import { listGradeChanges } from '../../lib/data-loaders';
import { buildRssFeed } from '../../lib/feed-generator';

export const GET: APIRoute = () => {
  const changes = listGradeChanges();
  const xml = buildRssFeed(changes);
  return new Response(xml, {
    headers: {
      'Content-Type': 'application/rss+xml; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
    },
  });
};
