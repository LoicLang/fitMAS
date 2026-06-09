export function decodePolyline(encoded?: string | null): [number, number][] {
  if (!encoded) return [];
  const points: [number, number][] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    let shift = 0;
    let result = 0;
    let byte = 0;

    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);

    lat += result & 1 ? ~(result >> 1) : result >> 1;

    shift = 0;
    result = 0;

    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);

    lng += result & 1 ? ~(result >> 1) : result >> 1;
    points.push([lat / 1e5, lng / 1e5]);
  }

  return points;
}

export interface RoutePath {
  path: string;
  viewBox: string;
}

/**
 * Build an SVG path for a route in its *own* bounding box, plus the matching
 * viewBox. The caller renders it with `preserveAspectRatio="xMidYMid meet"` so the
 * route fills the container at its true proportions (single fit — no fixed inner box
 * to letterbox into) and with `vector-effect="non-scaling-stroke"` so the line keeps
 * a constant screen width regardless of the (tiny, degree-scale) viewBox units.
 * Longitude is compressed by cos(latitude) so the shape stays geographically true.
 */
export function buildSvgPath(points: [number, number][]): RoutePath | null {
  if (points.length < 2) return null;

  const lats = points.map(([lat]) => lat);
  const avgLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const lngScale = Math.max(Math.cos((avgLat * Math.PI) / 180), 0.001);

  // North-up planar projection: x from longitude (compressed), y from negated latitude.
  const project = ([lat, lng]: [number, number]): [number, number] => [lng * lngScale, -lat];
  const xs = points.map((p) => project(p)[0]);
  const ys = points.map((p) => project(p)[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const w = Math.max(...xs) - minX || 0.0001;
  const h = Math.max(...ys) - minY || 0.0001;

  const path = points
    .map((p, index) => {
      const [px, py] = project(p);
      return `${index === 0 ? "M" : "L"} ${(px - minX).toFixed(6)} ${(py - minY).toFixed(6)}`;
    })
    .join(" ");

  const pad = Math.max(w, h) * 0.06;
  const viewBox = `${-pad} ${-pad} ${w + 2 * pad} ${h + 2 * pad}`;
  return { path, viewBox };
}
