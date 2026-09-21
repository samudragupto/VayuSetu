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
    return (
      <div>
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          NEXT_PUBLIC_GOOGLE_MAPS_API_KEY is not configured. Showing the hotspot list instead of the interactive map.
        </div>
        <FallbackList hotspots={hotspots} threshold={threshold} />
      </div>
    );
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
