type BrandMarkProps = {
  id: string;
};

export function BrandMark({ id }: BrandMarkProps) {
  return (
    <svg className="brand-mark" viewBox="0 0 48 48" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="6" y1="6" x2="42" y2="42" gradientUnits="userSpaceOnUse">
          <stop stopColor="#2578ff" />
          <stop offset="1" stopColor="#55c7e9" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="13" fill={`url(#${id})`} />
      <circle cx="18" cy="18" r="3.6" fill="#fff" />
      <circle cx="30" cy="18" r="3.6" fill="#fff" />
      <path
        d="M16 26v2c0 4.4 3.6 8 8 8s8-3.6 8-8v-2"
        fill="none"
        stroke="#fff"
        strokeLinecap="round"
        strokeWidth="5.5"
      />
    </svg>
  );
}
