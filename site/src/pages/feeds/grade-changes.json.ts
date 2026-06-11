import type { APIRoute } from 'astro';
import { listGradeChanges } from '../../lib/data-loaders';
import { buildJsonFeed } from '../../lib/feed-generator';

export const GET: APIRoute = () => {
  const changes = listGradeChanges();
  const feed = buildJsonFeed(changes);
  return new Response(JSON.stringify(feed, null, 2), {
    headers: {
      'Content-Type': 'application/feed+json; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
    },
  });
};
