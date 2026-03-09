import http from 'k6/http';
import { sleep } from 'k6';
import { Trend } from 'k6/metrics';

export const options = {
  vus: 20,
  duration: '30s',
  thresholds: {
    http_req_duration: ['p(95)<300'],
  },
};

const healthTrend = new Trend('health_req_duration');

export default function () {
  const base = __ENV.BASE_URL || 'http://localhost:8080';
  const url = `${base}/health`;
  const res = http.get(url);
  healthTrend.add(res.timings.duration);
  sleep(0.5);
}


