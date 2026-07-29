import type { ReactNode } from "react";

type IconProps = {
  size?: number;
  className?: string;
};

function Svg({
  size = 18,
  className,
  children,
}: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function IconDashboard(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </Svg>
  );
}

export function IconSources(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 19.5c1.2-3.2 3.6-4.8 7-4.8s5.8 1.6 7 4.8" />
      <path d="M19.5 8.5a7.5 7.5 0 0 0-15 0" opacity="0.55" />
    </Svg>
  );
}

export function IconAdd(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-3.2-3.2" />
      <path d="M11 8v6M8 11h6" />
    </Svg>
  );
}

export function IconLibrary(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="4" y="5" width="12" height="15" rx="1.5" />
      <path d="M16 8h3.5a1.5 1.5 0 0 1 1.5 1.5v10A1.5 1.5 0 0 1 19.5 21H8" />
      <path d="M8 9h4M8 13h4M8 17h2.5" />
    </Svg>
  );
}

export function IconRename(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0 0-3L17 4.5a2.1 2.1 0 0 0-3 0L4 16v4z" />
      <path d="M12.5 6.5l3 3" />
    </Svg>
  );
}

export function IconActivity(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 12h3.5l2-6 3.5 12 2.5-6H21" />
    </Svg>
  );
}

export function IconSettings(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M4.9 6.5l1.6 1.6M17.5 15.9l1.6 1.6M3.5 12h2.2M18.3 12h2.2M4.9 17.5l1.6-1.6M17.5 8.1l1.6-1.6" />
    </Svg>
  );
}

/** Servarr-style circular brand mark */
export function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 48 48"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="ytarrBrand" x1="8" y1="4" x2="42" y2="44">
          <stop stopColor="#3fb950" />
          <stop offset="1" stopColor="#238636" />
        </linearGradient>
      </defs>
      <circle cx="24" cy="24" r="22" fill="url(#ytarrBrand)" />
      <circle cx="24" cy="24" r="22" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="2" />
      {/* stylized play / Y hybrid like arr logos */}
      <path
        d="M20 15.5v17L34 24 20 15.5z"
        fill="#fff"
      />
      <path
        d="M14.5 33.5c2.8-4.2 6.2-6.3 9.5-6.3"
        fill="none"
        stroke="rgba(255,255,255,0.45)"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
