export const SITE_NAME = 'DeFi Risk';
export const SITE_DESCRIPTION =
  'A field guide for DeFi risk. Open-source rubric, neutral framing, candid about its own limitations.';
export const SITE_URL = 'https://defirisk.co';
export const DEFAULT_OG_IMAGE = '/og/default.png';
export const TWITTER_HANDLE = '@defirisk';

// Canonical public source repo. Used to build issue-template links for the
// corrections/disputes channels (see /corrections).
export const REPO_URL = 'https://github.com/0x-abdul/defirisk';
export const ISSUE_NEW_URL = `${REPO_URL}/issues/new`;

export const ORG_JSON_LD = {
  '@type': 'Organization',
  name: SITE_NAME,
  url: SITE_URL,
  description: SITE_DESCRIPTION,
  license: 'https://creativecommons.org/licenses/by/4.0/',
};

export const WEBSITE_JSON_LD = {
  '@type': 'WebSite',
  name: SITE_NAME,
  url: SITE_URL,
  description: SITE_DESCRIPTION,
};
