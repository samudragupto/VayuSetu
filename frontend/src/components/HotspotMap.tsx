"use client";

import { Circle, GoogleMap, InfoWindow, Marker, useJsApiLoader } from "@react-google-maps/api";
import { format } from "date-fns";
import { useCallback, useMemo, useState } from "react";

import { bandForAqi } from "@/lib/aqi";
import { labelForSource } from "@/lib/analytics";
import { config } from "@/lib/config";
import type { CitizenReport, PredictedHotspot } from "@/lib/types";

import { AqiBadge } from "./AqiBadge";
import { EmptyState, LoadingState } from "./States";

const MAP_CONTAINER_STYLE = { width: "100%", height: "100%" } as const;
const LIBRARIES: ("visualization" | "geometry")[] = ["geometry"];

// Approximate radius of a geohash-5 cell (4.9 km x 4.9 km) in metres.
const CELL_RADIUS_M = 2400;

interface HotspotMapProps {
  hotspots: PredictedHotspot[];
  reports: CitizenReport[];
  loading?: boolean;
  threshold: number;
  onSelectHotspot?: (hotspot: PredictedHotspot | null) => void;
}

function reportIcon(report: CitizenReport): google.maps.Symbol {
  const band = bandForAqi(report.estimatedAqi);
  return {
    path: google.maps.SymbolPath.CIRCLE,
    fillColor: band.color,
    fillOpacity: report.status === "analyzed" ? 0.9 : 0.4,
    strokeColor: "#ffffff",
    strokeWeight: 1,
    scale: 5,
  };
}

function FallbackList({ hotspots, threshold }: { hotspots: PredictedHotspot[]; threshold: number }) {
  if (hotspots.length === 0) {
    return <EmptyState title="No predicted hotspots in this window" description="Hotspots appear once the hourly batch prediction has processed citizen reports." />;
  }
  return (
    <div className="max-h-[420px] overflow-auto">
      <table className="table">
        <thead>
          <tr>
            <th>Cell</th>
            <th>City</th>
            <th>Predicted AQI</th>
            <th>Reports</th>
            <th>Alert</th>
          </tr>
        </thead>
        <tbody>
          {hotspots.map((hotspot) => (
            <tr key={hotspot.id} className={hotspot.predictedAqi >= threshold ? "bg-red-50" : undefined}>
              <td className="font-mono text-xs">{hotspot.geohash}</td>
              <td>{hotspot.city ?? "-"}</td>
              <td>
                <AqiBadge aqi={hotspot.predictedAqi} />
              </td>
              <td>{hotspot.reportCount}</td>
              <td className="text-xs">{hotspot.alertStatus.replace(/_/g, " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OfflineMap({ hotspots, reports, threshold, onSelectHotspot }: HotspotMapProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const locatedReports = useMemo(() => reports.filter((report) => report.location !== null).slice(0, 500), [reports]);
  const projection = useMemo(() => {
    const coordinates = [
      ...hotspots.map((hotspot) => ({ latitude: hotspot.latitude, longitude: hotspot.longitude })),
      ...locatedReports.flatMap((report) => (report.location ? [{ latitude: report.location.latitude, longitude: report.location.longitude }] : [])),
    ];
    if (coordinates.length === 0) {
      return null;
    }

    const minLatitude = Math.min(...coordinates.map((point) => point.latitude));
    const maxLatitude = Math.max(...coordinates.map((point) => point.latitude));
    const minLongitude = Math.min(...coordinates.map((point) => point.longitude));
    const maxLongitude = Math.max(...coordinates.map((point) => point.longitude));
    const latitudePadding = Math.max((maxLatitude - minLatitude) * 0.08, 0.25);
    const longitudePadding = Math.max((maxLongitude - minLongitude) * 0.08, 0.25);
    const south = minLatitude - latitudePadding;
    const north = maxLatitude + latitudePadding;
    const west = minLongitude - longitudePadding;
    const east = maxLongitude + longitudePadding;

    return {
      project(latitude: number, longitude: number) {
        return {
          x: 60 + ((longitude - west) / Math.max(east - west, 0.001)) * 880,
          y: 56 + ((north - latitude) / Math.max(north - south, 0.001)) * 400,
        };
      },
      cityLabels: Array.from(new Set(hotspots.map((hotspot) => hotspot.city).filter((city): city is string => Boolean(city))))
        .map((city) => {
          const points = hotspots.filter((hotspot) => hotspot.city === city);
          return {
            city,
            latitude: points.reduce((sum, point) => sum + point.latitude, 0) / points.length,
            longitude: points.reduce((sum, point) => sum + point.longitude, 0) / points.length,
          };
        })
        .slice(0, 14),
    };
  }, [hotspots, locatedReports]);

  const selected = hotspots.find((hotspot) => hotspot.id === selectedId) ?? null;
  if (!projection) {
    return <EmptyState title="No located reports or predicted hotspots" description="The offline map will populate when location data arrives." />;
  }

  const gridLines = Array.from({ length: 7 }, (_, index) => 60 + index * 145);
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900">
        <span><strong>Offline hotspot map</strong> · Google Maps key not configured; using the local demo view.</span>
        <span>{hotspots.length} cells · {locatedReports.length} located reports</span>
      </div>
      <div className="relative h-[480px] overflow-hidden bg-slate-100">
        <svg viewBox="0 0 1000 560" className="h-full w-full" role="img" aria-label="Offline map of predicted air quality hotspots and citizen reports">
          <defs>
            <pattern id="offline-map-grid" width="145" height="145" patternUnits="userSpaceOnUse">
              <path d="M 145 0 L 0 0 0 145" fill="none" stroke="#cbd5e1" strokeWidth="1" opacity="0.65" />
            </pattern>
            <linearGradient id="offline-map-wash" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stopColor="#e0f2fe" />
              <stop offset="1" stopColor="#f8fafc" />
            </linearGradient>
          </defs>
          <rect width="1000" height="560" fill="url(#offline-map-wash)" />
          <rect x="42" y="38" width="916" height="426" rx="18" fill="url(#offline-map-grid)" stroke="#94a3b8" strokeWidth="2" />
          {gridLines.map((position) => <path key={`road-${position}`} d={`M ${position - 90} 38 C ${position + 30} 150, ${position - 20} 280, ${position + 100} 464`} fill="none" stroke="#ffffff" strokeWidth="5" opacity="0.8" />)}
          {projection.cityLabels.map((label) => {
            const point = projection.project(label.latitude, label.longitude);
            return (
              <g key={label.city}>
                <circle cx={point.x} cy={point.y} r="4" fill="#334155" />
                <text x={point.x + 8} y={point.y - 8} fill="#334155" fontSize="13" fontWeight="600">{label.city}</text>
              </g>
            );
          })}
          {locatedReports.map((report) => {
            if (!report.location) {
              return null;
            }
            const point = projection.project(report.location.latitude, report.location.longitude);
            const color = report.estimatedAqi === null ? "#94a3b8" : bandForAqi(report.estimatedAqi).color;
            return <circle key={`report-${report.id}`} cx={point.x} cy={point.y} r="3.5" fill={color} fillOpacity={report.status === "analyzed" ? 0.8 : 0.35} stroke="#ffffff" strokeWidth="1" />;
          })}
          {hotspots.map((hotspot) => {
            const point = projection.project(hotspot.latitude, hotspot.longitude);
            const band = bandForAqi(hotspot.predictedAqi);
            const selectedHotspot = hotspot.id === selectedId;
            const radius = 8 + Math.min(22, Math.sqrt(Math.max(hotspot.reportCount, 1)) * 2);
            return (
              <g
                key={hotspot.id}
                role="button"
                tabIndex={0}
                aria-label={`${hotspot.city ?? "Hotspot"}, predicted AQI ${Math.round(hotspot.predictedAqi)}`}
                onClick={() => {
                  setSelectedId(hotspot.id);
                  onSelectHotspot?.(hotspot);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedId(hotspot.id);
                    onSelectHotspot?.(hotspot);
                  }
                }}
                className="cursor-pointer"
              >
                <circle cx={point.x} cy={point.y} r={radius + (selectedHotspot ? 5 : 0)} fill={band.color} fillOpacity="0.18" stroke={selectedHotspot ? "#0f172a" : band.color} strokeWidth={selectedHotspot ? 3 : 1.5} />
                <circle cx={point.x} cy={point.y} r="5" fill={band.color} stroke="#ffffff" strokeWidth="2" />
                <text x={point.x + radius + 4} y={point.y + 4} fill="#0f172a" fontSize="11" fontWeight="700">{Math.round(hotspot.predictedAqi)}</text>
              </g>
            );
          })}
          <text x="60" y="520" fill="#64748b" fontSize="12">Derived from citizen reports · cells are geohash-5 forecasts</text>
        </svg>
        <div className="pointer-events-none absolute bottom-4 right-4 rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs text-slate-700 shadow-sm">
          <p className="mb-1 font-semibold">Legend</p>
          <p><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-[#7e0023]" /> Forecast hotspot</p>
          <p><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-[#cc0033]" /> Citizen report</p>
          <p className="mt-1 text-slate-500">Click a hotspot for evidence</p>
        </div>
      </div>
      {selected ? (
        <div className="border-t border-slate-200 bg-white px-5 py-3 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            <strong>{selected.city ?? "Unnamed area"}</strong>
            <span className="font-mono text-xs text-slate-500">{selected.geohash}</span>
            <AqiBadge aqi={selected.predictedAqi} />
            <span className="text-xs text-slate-600">{selected.reportCount} reports · {(selected.confidence * 100).toFixed(0)}% confidence</span>
          </div>
          <p className="mt-1 text-xs text-slate-600">Likely sources: {selected.dominantSources.map(labelForSource).join(", ") || "mixed local sources"}. Alert status: {selected.alertStatus.replace(/_/g, " ")}.</p>
        </div>
      ) : null}
      <FallbackList hotspots={hotspots} threshold={threshold} />
    </div>
  );
}

export function HotspotMap({ hotspots, reports, loading, threshold, onSelectHotspot }: HotspotMapProps) {
  const [selected, setSelected] = useState<PredictedHotspot | null>(null);
  const [selectedReport, setSelectedReport] = useState<CitizenReport | null>(null);
  const [map, setMap] = useState<google.maps.Map | null>(null);
  const hasKey = Boolean(config.googleMapsApiKey);

  const { isLoaded, loadError } = useJsApiLoader({
    id: "vayusetu-google-maps",
    googleMapsApiKey: config.googleMapsApiKey || "missing",
    libraries: LIBRARIES,
    preventGoogleFontsLoading: true,
  });

  const locatedReports = useMemo(() => reports.filter((report) => report.location !== null).slice(0, 400), [reports]);

  const center = useMemo(() => {
    if (hotspots.length > 0) {
      const top = hotspots[0]!;
      return { lat: top.latitude, lng: top.longitude };
    }
    const first = locatedReports[0];
    if (first?.location) {
      return { lat: first.location.latitude, lng: first.location.longitude };
    }
    return config.defaultCenter;
  }, [hotspots, locatedReports]);

  const handleLoad = useCallback(
    (instance: google.maps.Map) => {
      setMap(instance);
      if (hotspots.length > 1) {
        const bounds = new google.maps.LatLngBounds();
        for (const hotspot of hotspots) {
          bounds.extend({ lat: hotspot.latitude, lng: hotspot.longitude });
        }
        instance.fitBounds(bounds, 48);
      }
    },
    [hotspots]
  );

  const selectHotspot = useCallback(
    (hotspot: PredictedHotspot | null) => {
      setSelected(hotspot);
      setSelectedReport(null);
      onSelectHotspot?.(hotspot);
      if (hotspot && map) {
        map.panTo({ lat: hotspot.latitude, lng: hotspot.longitude });
      }
    },
    [map, onSelectHotspot]
  );

  if (!hasKey) {
    return <OfflineMap hotspots={hotspots} reports={reports} threshold={threshold} onSelectHotspot={onSelectHotspot} />;
  }

  if (loadError) {
    return (
      <div>
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">Google Maps failed to load: {loadError.message}</div>
        <FallbackList hotspots={hotspots} threshold={threshold} />
      </div>
    );
  }

  if (!isLoaded) {
    return (
      <div className="flex h-[420px] items-center justify-center">
        <LoadingState message="Loading Google Maps" />
      </div>
    );
  }

  return (
    <div className="relative h-[480px] w-full">
      <GoogleMap
        mapContainerStyle={MAP_CONTAINER_STYLE}
        center={center}
        zoom={10}
        onLoad={handleLoad}
        onClick={() => selectHotspot(null)}
        options={{
          mapId: config.googleMapsMapId,
          streetViewControl: false,
          mapTypeControl: false,
          fullscreenControl: true,
          clickableIcons: false,
          gestureHandling: "greedy",
        }}
      >
        {hotspots.map((hotspot) => {
          const band = bandForAqi(hotspot.predictedAqi);
          const critical = hotspot.predictedAqi >= threshold;
          return (
            <Circle
              key={hotspot.id}
              center={{ lat: hotspot.latitude, lng: hotspot.longitude }}
              radius={CELL_RADIUS_M}
              onClick={() => selectHotspot(hotspot)}
              options={{
                fillColor: band.color,
                fillOpacity: critical ? 0.45 : 0.3,
                strokeColor: critical ? "#7e0023" : band.color,
                strokeOpacity: 0.9,
                strokeWeight: critical ? 3 : 1.5,
                clickable: true,
                zIndex: Math.round(hotspot.predictedAqi),
              }}
            />
          );
        })}

        {locatedReports.map((report) => (
          <Marker
            key={report.id}
            position={{ lat: report.location!.latitude, lng: report.location!.longitude }}
            icon={reportIcon(report)}
            title={report.city ?? report.id}
            onClick={() => {
              setSelected(null);
              setSelectedReport(report);
            }}
          />
        ))}

        {selected ? (
          <InfoWindow position={{ lat: selected.latitude, lng: selected.longitude }} onCloseClick={() => selectHotspot(null)}>
            <div className="max-w-xs space-y-1 text-sm text-slate-800">
              <p className="font-semibold">
                {selected.city ?? "Unnamed area"} <span className="font-mono text-xs text-slate-500">{selected.geohash}</span>
              </p>
              <p>
                12 h forecast: <AqiBadge aqi={selected.predictedAqi} />
              </p>
              <p className="text-xs text-slate-600">
                Current estimate {selected.currentAqiEstimate !== null ? Math.round(selected.currentAqiEstimate) : "n/a"} from {selected.reportCount} report{selected.reportCount === 1 ? "" : "s"}; confidence {(selected.confidence * 100).toFixed(0)}%
              </p>
              {selected.dominantSources.length > 0 ? <p className="text-xs text-slate-600">Likely sources: {selected.dominantSources.map(labelForSource).join(", ")}</p> : null}
              <p className="text-xs text-slate-500">
                Forecast for {selected.forecastFor ? format(selected.forecastFor, "dd MMM HH:mm") : "n/a"}; alert status {selected.alertStatus.replace(/_/g, " ")}
              </p>
            </div>
          </InfoWindow>
        ) : null}

        {selectedReport?.location ? (
          <InfoWindow position={{ lat: selectedReport.location.latitude, lng: selectedReport.location.longitude }} onCloseClick={() => setSelectedReport(null)}>
            <div className="max-w-xs space-y-1 text-sm text-slate-800">
              <p className="font-semibold">Citizen report {selectedReport.id.slice(0, 8).toUpperCase()}</p>
              <p>{selectedReport.status === "analyzed" ? <AqiBadge aqi={selectedReport.estimatedAqi} /> : <span className="text-xs text-slate-500">Status: {selectedReport.status}</span>}</p>
              {selectedReport.hazeIndex !== null ? (
                <p className="text-xs text-slate-600">
                  Haze index {selectedReport.hazeIndex.toFixed(2)}; visibility {selectedReport.visibilityKm !== null ? `${selectedReport.visibilityKm.toFixed(1)} km` : "n/a"}
                </p>
              ) : null}
              {selectedReport.pollutionSources.length > 0 ? <p className="text-xs text-slate-600">Sources: {selectedReport.pollutionSources.map(labelForSource).join(", ")}</p> : null}
              <p className="text-xs text-slate-500">{selectedReport.createdAt ? format(selectedReport.createdAt, "dd MMM HH:mm") : ""}</p>
            </div>
          </InfoWindow>
        ) : null}
      </GoogleMap>

      <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-white/90 px-3 py-2 text-xs text-slate-700 shadow">
        <p className="font-semibold">Legend</p>
        <p>Circles: predicted 12 h AQI per 5 km cell</p>
        <p>Dots: citizen reports coloured by estimated AQI</p>
        <p>Thick red border: above alert threshold ({threshold})</p>
      </div>
      {loading ? (
        <div className="absolute right-3 top-3 rounded-md bg-white/90 px-3 py-1 shadow">
          <LoadingState message="Updating" />
        </div>
      ) : null}
    </div>
  );
}
