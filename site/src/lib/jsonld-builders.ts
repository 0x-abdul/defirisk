import { SITE_NAME, SITE_URL, ORG_JSON_LD } from './seo-defaults';
import { RUBRIC_VERSION } from './rubric';

const CONTEXT = 'https://schema.org';

export function buildBreadcrumbList(
  items: Array<{ name: string; url: string }>,
): object {
  return {
    '@context': CONTEXT,
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: item.name,
      item: item.url.startsWith('http') ? item.url : `${SITE_URL}${item.url}`,
    })),
  };
}

export function buildDataset(opts: {
  name: string;
  description: string;
  url: string;
  apiUrl: string;
  dateModified?: string;
}): object {
  return {
    '@context': CONTEXT,
    '@type': 'Dataset',
    name: opts.name,
    description: opts.description,
    url: opts.url.startsWith('http') ? opts.url : `${SITE_URL}${opts.url}`,
    creator: { ...ORG_JSON_LD },
    license: 'https://creativecommons.org/licenses/by/4.0/',
    version: RUBRIC_VERSION,
    distribution: [
      {
        '@type': 'DataDownload',
        encodingFormat: 'application/json',
        contentUrl: opts.apiUrl.startsWith('http')
          ? opts.apiUrl
          : `${SITE_URL}${opts.apiUrl}`,
      },
    ],
    ...(opts.dateModified ? { dateModified: opts.dateModified } : {}),
  };
}

export function buildNewsArticle(opts: {
  headline: string;
  description: string;
  url: string;
  datePublished?: string;
  dateModified?: string;
}): object {
  return {
    '@context': CONTEXT,
    '@type': 'NewsArticle',
    headline: opts.headline.slice(0, 110),
    description: opts.description,
    url: opts.url.startsWith('http') ? opts.url : `${SITE_URL}${opts.url}`,
    publisher: { ...ORG_JSON_LD },
    author: { '@type': 'Organization', name: SITE_NAME },
    articleSection: 'DeFi Security Incidents',
    ...(opts.datePublished ? { datePublished: opts.datePublished } : {}),
    ...(opts.dateModified ? { dateModified: opts.dateModified } : {}),
  };
}

export function buildDefinedTerm(opts: {
  name: string;
  description: string;
  url: string;
}): object {
  return {
    '@context': CONTEXT,
    '@type': 'DefinedTerm',
    name: opts.name,
    description: opts.description,
    url: opts.url.startsWith('http') ? opts.url : `${SITE_URL}${opts.url}`,
    inDefinedTermSet: `${SITE_URL}/methodology/`,
    termCode: opts.url.split('/').filter(Boolean).pop() ?? '',
  };
}

export function buildTechArticle(opts: {
  name: string;
  description: string;
  url: string;
}): object {
  return {
    '@context': CONTEXT,
    '@type': 'TechArticle',
    name: opts.name,
    description: opts.description,
    url: opts.url.startsWith('http') ? opts.url : `${SITE_URL}${opts.url}`,
    author: { '@type': 'Organization', name: SITE_NAME },
    publisher: { ...ORG_JSON_LD },
    license: 'https://creativecommons.org/licenses/by/4.0/',
  };
}

export function buildSiteWide(): object[] {
  return [
    { '@context': CONTEXT, ...ORG_JSON_LD },
    {
      '@context': CONTEXT,
      '@type': 'WebSite',
      name: SITE_NAME,
      url: SITE_URL,
      potentialAction: {
        '@type': 'SearchAction',
        target: {
          '@type': 'EntryPoint',
          urlTemplate: `${SITE_URL}/protocols/?q={search_term_string}`,
        },
        'query-input': 'required name=search_term_string',
      },
    },
  ];
}
