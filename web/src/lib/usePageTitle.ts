import { useEffect } from "react";

export const SITE_NAME = "wildlife-radar";

export function pageTitle(title: string | null | undefined): string {
  return title ? `${title} · ${SITE_NAME}` : SITE_NAME;
}

/** Set the document title for the current page (screen readers announce it on navigation). */
export function usePageTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = pageTitle(title);
  }, [title]);
}
