type BrandMarkProps = {
  id: string;
};

export function BrandMark({ id }: BrandMarkProps) {
  const shadowId = `${id}-shadow`;

  return (
    <svg className="brand-mark" viewBox="30 30 160 160" aria-hidden="true">
      <defs>
        <filter id={shadowId} x="0" y="0" width="220" height="220" filterUnits="userSpaceOnUse">
          <feDropShadow dx="0" dy="0" stdDeviation="15" floodColor="#2570ff" floodOpacity="0.1" />
        </filter>
        <linearGradient id={id} x1="190" y1="190" x2="30" y2="30" gradientUnits="userSpaceOnUse">
          <stop stopColor="#63d5f1" />
          <stop offset="1" stopColor="#2570ff" />
        </linearGradient>
      </defs>
      <g filter={`url(#${shadowId})`}>
        <rect x="30" y="30" width="160" height="160" rx="40" fill={`url(#${id})`} />
        <path
          d="M144 117.574C144 123.648 142.547 128.977 139.64 133.561C136.733 138.144 132.621 141.698 127.304 144.219C122.025 146.74 115.904 148 108.942 148C102.019 148 95.9182 146.74 90.6396 144.219C85.361 141.698 81.2675 138.144 78.3604 133.561C75.4534 128.977 74 123.648 74 117.574V110H93.5078V115.913C93.5079 118.816 94.1586 121.413 95.459 123.705C96.7978 125.997 98.6335 127.793 100.967 129.092C103.3 130.391 105.959 131.04 108.942 131.04C112.041 131.04 114.757 130.39 117.09 129.092C119.423 127.793 121.221 125.997 122.483 123.705C123.784 121.413 124.435 118.816 124.435 115.913V110H144V117.574Z"
          fill="#fff"
        />
      </g>
      <circle cx="83.5" cy="86.5" r="9.5" fill="#fff" />
      <circle cx="134" cy="86" r="10" fill="#fff" />
    </svg>
  );
}
