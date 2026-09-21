/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export served by Firebase Hosting (no Node.js server required).
  output: "export",
  trailingSlash: true,
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
  eslint: { dirs: ["src"] },
};

export default nextConfig;
