/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_STATIC_BASE?: string;
  readonly VITE_API_BASE?: string;
  readonly VITE_REGIONS?: string;
  readonly VITE_BASEMAP_STYLE?: string;
  readonly VITE_BASEMAP_STYLE_DARK?: string;
  readonly VITE_SOURCE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
