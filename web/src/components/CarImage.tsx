/* eslint-disable @next/next/no-img-element */
import type { SnapshotCar } from "@/lib/types";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export function imageSrc(c: SnapshotCar): string | null {
  const src = c.image ?? c.image_url ?? null;
  if (!src) return null;
  return src.startsWith("/") ? `${BASE_PATH}${src}` : src;
}

export function CarImage({ car, className = "" }: { car: SnapshotCar; className?: string }) {
  const src = imageSrc(car);
  if (src) {
    return <img src={src} alt={`${car.make} ${car.model}`} className={`h-full w-full object-cover ${className}`} loading="lazy" />;
  }
  return (
    <div className={`flex h-full w-full flex-col items-center justify-center bg-gray-800 text-gray-500 ${className}`}>
      <svg viewBox="0 0 64 40" className="h-10 w-16 fill-current opacity-60" aria-hidden="true">
        <path d="M8 26h48l-5-10a4 4 0 0 0-3.7-2.6H16.7A4 4 0 0 0 13 16z" />
        <rect x="6" y="24" width="52" height="9" rx="3" />
        <circle cx="18" cy="34" r="4" /><circle cx="46" cy="34" r="4" />
      </svg>
      <span className="mt-1 text-xs">no photo yet</span>
    </div>
  );
}
