/**
 * OpenStreetMap view shared by the worker and admin maps.
 *
 * OSM is the BACKDROP, never the source of safety data. Every marker here comes from a worker
 * report or an admin decision; nothing is inferred from the map itself.
 *
 * The two callers pass different marker sets, which is how the privacy boundary is kept visible:
 * the worker map is only ever handed published alerts, so there is no filtering logic here that
 * could be got wrong — a worker payload simply never contains a raw report.
 */
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { Fragment, useEffect } from 'react';
import { Circle, MapContainer, Marker, Polyline, Popup, TileLayer, useMap, useMapEvents } from 'react-leaflet';

/** Leaflet's default marker icons are bundler-hostile; inline SVG avoids the asset plumbing. */
function pin(color: string, pulse = false) {
  return L.divIcon({
    className: '',
    html: `<span style="display:block;width:18px;height:18px;border-radius:9999px;
      background:${color};border:2.5px solid #fff;box-shadow:0 1px 6px rgba(0,0,0,.4)
      ${pulse ? ';animation:none' : ''}"></span>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

const ICONS = {
  report: pin('#64748b'),
  start: pin('#2563eb'),
  destination: pin('#7c3aed'),
  candidate: pin('#dc2626'),
  investigating: pin('#d97706'),
  published: pin('#dc2626'),
  resolved: pin('#059669'),
  me: pin('#2563eb'),
};

export type MapMarker = {
  id: string | number;
  latitude: number;
  longitude: number;
  kind: keyof typeof ICONS;
  title: string;
  body?: string;
  /** Drawn as a translucent disc — used for the 1 km hotspot radius. */
  radiusMeters?: number;
  onSelect?: () => void;
};

/** Lets the worker drop a pin when GPS is denied or wrong. Only mounted when `onPick` is given,
 *  so the admin and alert maps stay read-only and cannot have a location set by a stray click. */
function PickLocation({ onPick }: { onPick: (latitude: number, longitude: number) => void }) {
  useMapEvents({ click: (event) => onPick(event.latlng.lat, event.latlng.lng) });
  return null;
}

/** A calculated path drawn on the map. Several can coexist so two route options can be compared. */
export type RouteLine = {
  id: string;
  positions: Array<[number, number]>;
  color: string;
  /** The route the worker is currently looking at, drawn thicker and more opaque. */
  emphasis?: boolean;
  dashed?: boolean;
};

/** Frame a whole route at once. Separate from `Recenter`, which only moves the centre. */
function FitTo({ bounds }: { bounds: Array<[number, number]> | null }) {
  const map = useMap();
  const key = bounds ? bounds.map((b) => `${b[0].toFixed(5)},${b[1].toFixed(5)}`).join(';') : '';
  useEffect(() => {
    if (bounds && bounds.length > 1) {
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 16 });
    }
  }, [key, map]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** Imperatively recentre when the caller changes `center` (Find My Location / Search). */
function Recenter({ center, zoom }: { center: [number, number] | null; zoom?: number }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.flyTo(center, zoom ?? map.getZoom(), { duration: 0.8 });
  }, [center, zoom, map]);
  return null;
}

export function SafetyMap({
  markers,
  center,
  zoom = 14,
  height = 420,
  recenterTo = null,
  onPick,
  routes = [],
  fitBounds = null,
}: {
  markers: MapMarker[];
  center: [number, number];
  zoom?: number;
  height?: number;
  recenterTo?: [number, number] | null;
  /** When supplied, clicking the map reports the clicked coordinate. Omit for a read-only map. */
  onPick?: (latitude: number, longitude: number) => void;
  /** Calculated route polylines. Drawn beneath the markers so pins stay clickable. */
  routes?: RouteLine[];
  /** Fit the view to these bounds once — used to frame a freshly calculated route. */
  fitBounds?: Array<[number, number]> | null;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-black/[0.08]" style={{ height }}>
      <MapContainer center={center} zoom={zoom} scrollWheelZoom style={{ height: '100%', width: '100%' }}>
        {/* Standard OSM raster tiles. Attribution is required by the OSM tile usage policy. */}
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
        <Recenter center={recenterTo} />
        <FitTo bounds={fitBounds} />
        {onPick && <PickLocation onPick={onPick} />}
        {routes.map((line) => (
          <Polyline
            key={line.id}
            positions={line.positions}
            pathOptions={{
              color: line.color,
              weight: line.emphasis ? 5 : 3.5,
              opacity: line.emphasis ? 0.95 : 0.55,
              dashArray: line.dashed ? '7 7' : undefined,
            }}
          />
        ))}
        {markers.map((marker) => (
          <Fragment key={`${marker.kind}-${marker.id}`}>
            {marker.radiusMeters ? (
              <Circle
                center={[marker.latitude, marker.longitude]}
                radius={marker.radiusMeters}
                pathOptions={{
                  color: marker.kind === 'resolved' ? '#059669' : marker.kind === 'investigating' ? '#d97706' : '#dc2626',
                  fillOpacity: 0.08,
                  weight: 1.5,
                }}
              />
            ) : null}
            <Marker
              position={[marker.latitude, marker.longitude]}
              icon={ICONS[marker.kind]}
              eventHandlers={marker.onSelect ? { click: marker.onSelect } : undefined}
            >
              <Popup>
                <strong style={{ fontSize: 13 }}>{marker.title}</strong>
                {marker.body && <p style={{ margin: '4px 0 0', fontSize: 12 }}>{marker.body}</p>}
              </Popup>
            </Marker>
          </Fragment>
        ))}
      </MapContainer>
    </div>
  );
}
