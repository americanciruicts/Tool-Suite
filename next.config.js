/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  experimental: {
    outputFileTracingRoot: undefined,
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  eslint: {
    // Lint is a separate CI/dev concern; don't fail the production build on
    // style rules (e.g. react/no-unescaped-entities in long copy strings).
    ignoreDuringBuilds: true,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `http://${process.env.API_HOST || 'backend'}:8000/api/:path*`,
      },
    ];
  },
}

module.exports = nextConfig