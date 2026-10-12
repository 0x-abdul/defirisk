/// <reference path="../.astro/types.d.ts" />
/// <reference types="astro/client" />

interface ImportMetaEnv {
  readonly DEFIRISK_REPOSITORY_ROOT?: string;
  readonly PUBLIC_GIT_SHA: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
