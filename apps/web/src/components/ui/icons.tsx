/**
 * The only icons in GRIDWISE (decision 0015): 16 px, 1.5 px stroke, square caps, drawn here.
 * Decorative: always paired with a visible or screen-reader label.
 */

import type { ReactNode } from "react";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="square"
      className="shrink-0"
    >
      {children}
    </svg>
  );
}

/** The product mark: a bus bar with three feeders. */
export function MarkIcon() {
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18" className="shrink-0">
      <rect x="1" y="3" width="16" height="3" fill="currentColor" />
      <path d="M4 6v9M9 6v9M14 6v9" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

export const DashboardIcon = () => (
  <Icon>
    <path d="M2.5 2.5h4.5v6h-4.5zM9 2.5h4.5v3.5H9zM9 8h4.5v5.5H9zM2.5 10.5h4.5v3H2.5z" />
  </Icon>
);

export const GridIcon = () => (
  <Icon>
    <path d="M2 4h12M5 4v4M11 4v4M3 8h4M9 8h4M5 8v4M11 8v4M3.5 12h3M9.5 12h3" />
  </Icon>
);

export const SimulationIcon = () => (
  <Icon>
    <path d="M2 13.5h12M3 11l3-4 3 2.5L13.5 3" />
  </Icon>
);

export const AssetsIcon = () => (
  <Icon>
    <path d="M2.5 3h11M2.5 6.5h11M2.5 10h11M2.5 13.5h7" />
  </Icon>
);

export const MenuIcon = () => (
  <Icon>
    <path d="M2 4h12M2 8h12M2 12h12" />
  </Icon>
);

export const CloseIcon = () => (
  <Icon>
    <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
  </Icon>
);

export const ZoomInIcon = () => (
  <Icon>
    <path d="M7 4v6M4 7h6M10.5 10.5L14 14" />
    <circle cx="7" cy="7" r="4.75" />
  </Icon>
);

export const ZoomOutIcon = () => (
  <Icon>
    <path d="M4 7h6M10.5 10.5L14 14" />
    <circle cx="7" cy="7" r="4.75" />
  </Icon>
);

export const FitIcon = () => (
  <Icon>
    <path d="M2 5.5V2h3.5M10.5 2H14v3.5M14 10.5V14h-3.5M5.5 14H2v-3.5" />
  </Icon>
);
