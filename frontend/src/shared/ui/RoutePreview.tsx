import { buildSvgPath, decodePolyline } from "../../lib/polyline";

export function RoutePreview({ polyline }: { polyline?: string | null }) {
  const route = buildSvgPath(decodePolyline(polyline));

  return (
    <div className="relative aspect-[4/3] max-h-[22rem] w-full overflow-hidden rounded-[2rem] border border-black/6 bg-zinc-50 md:aspect-[16/9]">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_30%,rgba(255,107,53,0.12),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.4),transparent_35%)]" />
      <div className="absolute inset-0 opacity-30 [background-image:linear-gradient(135deg,rgba(0,0,0,0.05)_2px,transparent_2px),linear-gradient(45deg,rgba(0,0,0,0.03)_2px,transparent_2px)] [background-size:2.4rem_2.4rem]" />
      {route ? (
        <svg data-testid="route-map" viewBox={route.viewBox} preserveAspectRatio="xMidYMid meet" className="relative h-full w-full p-6">
          <path d={route.path} vectorEffect="non-scaling-stroke" className="fill-none stroke-[rgba(255,107,53,0.2)] [stroke-linecap:round] [stroke-linejoin:round] [stroke-width:8px]" />
          <path d={route.path} vectorEffect="non-scaling-stroke" className="fill-none stroke-[var(--accent)] [stroke-linecap:round] [stroke-linejoin:round] [stroke-width:4px] [filter:drop-shadow(0_0_10px_rgba(255,107,53,0.28))]" />
        </svg>
      ) : (
        <div className="h-full w-full" />
      )}
      <div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-white to-transparent" />
    </div>
  );
}
