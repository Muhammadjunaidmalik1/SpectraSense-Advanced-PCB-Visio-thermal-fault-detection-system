<script setup>
import { ref, computed } from 'vue';
import LiveStream from '../components/LiveStream.vue';
import StreamControls from '../components/StreamControls.vue';
import ConnectionStatus from '../components/ConnectionStatus.vue';
import SolderingTimer from '../components/SolderingTimer.vue';

const defaultUrl = 'http://192.168.136.100/liveView';

/* camera view selection: 'rgb' | 'thermal' | 'combined' */
const cameraView = ref('rgb');

const streamUrl = ref(defaultUrl);
const mode = ref('iframe'); // 'iframe' | 'video'
const isPlaying = ref(true);
const lastError = ref(null);
const lastUpdated = ref(new Date());
const latencyMs = ref(80); // fake for now

const temperatureC = ref(null);
const statusMessages = ref([]);

/* camera view labels */

const cameraViewLabel = computed(() => {
  switch (cameraView.value) {
    case 'thermal':
      return 'Thermal Sensor';
    case 'combined':
      return 'Combined View';
    default:
      return 'RGB Camera';
  }
});

/* Stream handlers (RGB camera) */

function handleReload() {
  lastUpdated.value = new Date();
}

function handlePlay() {
  isPlaying.value = true;
  lastError.value = null;
}

function handlePause() {
  isPlaying.value = false;
}

function handleError(event) {
  console.error('Stream error', event);
  lastError.value = 'Failed to load stream. Check camera or CORS settings.';
}

// If you later want settings from backend, hook them in here
function handleSettingsUpdate(payload) {
  if (payload.url !== undefined) {
    streamUrl.value = payload.url || defaultUrl;
  }
  if (payload.mode !== undefined) {
    mode.value = payload.mode;
  }
}

/* Status derived */

const statusText = computed(() => {
  if (lastError.value) return 'Error';
  return isPlaying.value ? 'Live' : 'Paused';
});

const statusLevel = computed(() => {
  if (lastError.value) return 'error';
  return isPlaying.value ? 'ok' : 'idle';
});

/* Status messages helper */

function pushStatusMessage(message) {
  statusMessages.value = [
    {
      id: Date.now() + Math.random(),
      message,
      timestamp: new Date(),
    },
    ...statusMessages.value,
  ];
}

const sortedMessages = computed(() =>
    [...statusMessages.value].sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
    ),
);

/* Test actions – later become backend calls */

function testFetchTemperature() {
  const fake = 220 + Math.random() * 40; // 220–260 °C
  temperatureC.value = Math.round(fake * 10) / 10;
  pushStatusMessage(`Fetched temperature: ${temperatureC.value} °C (test data)`);
}

function testFetchStatusMessages() {
  const samples = [
    'Flux applied – ready to solder.',
    'Soldering tip cleaned.',
    'Warning: temperature slightly below target.',
    'Profile: lead-free reflow selected.',
  ];
  const sample = samples[Math.floor(Math.random() * samples.length)];
  pushStatusMessage(sample + ' (test)');
}

/* NEW: test calls for thermal / combined views */

function testThermalFrame() {
  // later: call backend endpoint, e.g. GET /api/thermal/frame
  pushStatusMessage('Requested thermal sensor frame from backend (test only).');
}

function testCombinedFrame() {
  // later: call backend endpoint, e.g. GET /api/combined/frame
  pushStatusMessage('Requested combined RGB + thermal frame (test only).');
}

/* Timer evaluation callback */

function handleTimerEvaluation(payload) {
  const seconds = payload.durationSec.toFixed(1);
  pushStatusMessage(
      `Soldering cycle: ${seconds}s – ${payload.rating} (test evaluation).`,
  );
}
</script>

<template>
  <div class="home-layout">
    <!-- LEFT: camera views + timer -->
    <section class="card" aria-label="Camera views">
      <div class="card-header">
        <div>
          <div class="card-title">{{ cameraViewLabel }}</div>
          <div class="card-subtitle">
            <span v-if="cameraView === 'rgb'">
              RGB livefeed · Mode: <strong>{{ mode }}</strong>
            </span>
            <span v-else-if="cameraView === 'thermal'">
              Thermal sensor visualization (backend integration pending)
            </span>
            <span v-else>
              Combined RGB + thermal (backend integration pending)
            </span>
          </div>
          <div
              v-if="cameraView === 'rgb'"
              class="text-muted"
              style="margin-top: 0.25rem;"
          >
            Viewing: <code>{{ streamUrl }}</code>
          </div>
        </div>

        <div class="btn-row">
          <button
              v-if="cameraView === 'rgb'"
              class="btn primary"
              @click="handleReload"
          >
            <span class="btn-icon">🔄</span>
            Reload stream
          </button>
        </div>
      </div>

      <!-- NEW: view selector tabs -->
      <div class="tab-row">
        <button
            type="button"
            class="tab"
            :class="{ active: cameraView === 'rgb' }"
            @click="cameraView = 'rgb'"
        >
          RGB Camera
        </button>
        <button
            type="button"
            class="tab"
            :class="{ active: cameraView === 'thermal' }"
            @click="cameraView = 'thermal'"
        >
          Thermal Sensor
        </button>
        <button
            type="button"
            class="tab"
            :class="{ active: cameraView === 'combined' }"
            @click="cameraView = 'combined'"
        >
          Combined View
        </button>
      </div>

      <!-- CAMERA VIEW CONTENT -->
      <!-- RGB CAMERA: existing livestream -->
      <template v-if="cameraView === 'rgb'">
        <LiveStream
            :src="streamUrl"
            :mode="mode"
            :playing="isPlaying"
            :reload-key="lastUpdated.getTime()"
            @error="handleError"
        />

        <div style="margin-top: 0.75rem;">
          <StreamControls
              :playing="isPlaying"
              @play="handlePlay"
              @pause="handlePause"
              @reload="handleReload"
          />
        </div>
      </template>

      <!-- THERMAL SENSOR VIEW (backend integration later) -->
      <template v-else-if="cameraView === 'thermal'">
        <div class="stream-container stream-placeholder">
          <div class="placeholder-content">
            <div class="placeholder-title">Thermal Sensor View</div>
            <div class="placeholder-text">
              Thermal image or heatmap from the backend will be rendered here
              (e.g. as live frames or snapshots).
            </div>
          </div>
        </div>

        <div class="btn-row" style="margin-top: 0.75rem;">
          <button
              type="button"
              class="btn primary"
              @click="testThermalFrame"
          >
            <span class="btn-icon">🔥</span>
            Test thermal backend request
          </button>
        </div>
      </template>

      <!-- COMBINED VIEW (backend integration later) -->
      <template v-else>
        <div class="stream-container stream-placeholder">
          <div class="placeholder-content">
            <div class="placeholder-title">Combined RGB + Thermal View</div>
            <div class="placeholder-text">
              Fused RGB and thermal data (overlay, side-by-side, etc.) will be
              provided by the backend and rendered here.
            </div>
          </div>
        </div>

        <div class="btn-row" style="margin-top: 0.75rem;">
          <button
              type="button"
              class="btn primary"
              @click="testCombinedFrame"
          >
            <span class="btn-icon">🧪</span>
            Test combined backend request
          </button>
        </div>
      </template>

      <!-- Timer is the same for all views -->
      <div
          style="
          margin-top: 1rem;
          border-top: 1px solid rgba(148, 163, 184, 0.35);
          padding-top: 0.75rem;
        "
      >
        <h3 style="font-size: 0.9rem; margin: 0 0 0.5rem;">Soldering timer</h3>
        <SolderingTimer @evaluation="handleTimerEvaluation" />
      </div>
    </section>

    <!-- RIGHT: status + temperature + messages -->
    <section style="display: flex; flex-direction: column; gap: 0.75rem;">
      <div class="card" aria-label="Connection and temperature status">
        <div class="card-header">
          <div class="card-title">Status &amp; Temperature</div>
        </div>

        <ConnectionStatus
            :status="statusText"
            :level="statusLevel"
            :last-updated="lastUpdated"
            :latency-ms="latencyMs"
            :error="lastError"
            :temperature-c="temperatureC"
            :messages="sortedMessages"
        />

        <div class="btn-row" style="margin-top: 0.75rem;">
          <button class="btn primary" type="button" @click="testFetchTemperature">
            <span class="btn-icon">🌡</span>
            Test temperature request
          </button>
          <button class="btn" type="button" @click="testFetchStatusMessages">
            <span class="btn-icon">💬</span>
            Add test status message
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
