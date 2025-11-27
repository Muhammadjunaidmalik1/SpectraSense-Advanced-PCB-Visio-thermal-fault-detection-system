<script setup>
import { ref, computed, onUnmounted } from 'vue';
import { PlayIcon, StopIcon, ArrowPathIcon } from '@heroicons/vue/24/outline';

const emit = defineEmits(['evaluation']);

const startTime = ref(null);
const currentTime = ref(null);
const endTime = ref(null);
const timerId = ref(null);
const evaluation = ref(null);

const isRunning = computed(() => !!startTime.value && !endTime.value);

const durationSec = computed(() => {
  if (!startTime.value) return null;
  const end = endTime.value || currentTime.value || new Date();
  return (end.getTime() - startTime.value.getTime()) / 1000;
});

function formatTime(date) {
  return date ? date.toLocaleTimeString() : '—';
}

function evaluateDuration(seconds) {
  if (seconds < 3) return 'Too short';
  if (seconds < 5) return 'Slightly short';
  if (seconds <= 8) return 'Optimal';
  if (seconds <= 12) return 'Slightly long';
  return 'Too long';
}

function start() {
  const now = new Date();
  startTime.value = now;
  currentTime.value = now;
  endTime.value = null;
  evaluation.value = null;

  if (timerId.value) {
    clearInterval(timerId.value);
  }
  timerId.value = setInterval(() => {
    currentTime.value = new Date();
  }, 500);
}

function stop() {
  if (!startTime.value) return;

  endTime.value = new Date();
  if (timerId.value) {
    clearInterval(timerId.value);
    timerId.value = null;
  }

  const seconds = durationSec.value || 0;
  evaluation.value = evaluateDuration(seconds);

  emit('evaluation', {
    start: startTime.value,
    end: endTime.value,
    durationSec: seconds,
    rating: evaluation.value,
  });
}

function reset() {
  if (timerId.value) {
    clearInterval(timerId.value);
    timerId.value = null;
  }
  startTime.value = null;
  currentTime.value = null;
  endTime.value = null;
  evaluation.value = null;
}

onUnmounted(() => {
  if (timerId.value) {
    clearInterval(timerId.value);
  }
});

const durationLabel = computed(() => {
  if (durationSec.value == null) return '—';
  return `${durationSec.value.toFixed(1)} s`;
});

const evaluationColor = computed(() => {
  switch (evaluation.value) {
    case 'Too short':
    case 'Too long':
      return '#dc2626';
    case 'Slightly short':
    case 'Slightly long':
      return '#eab308';
    case 'Optimal':
      return '#16a34a';
    default:
      return '#111827';
  }
});
</script>

<template>
  <div>
    <table class="kv-table">
      <tr>
        <td>Start time</td>
        <td>{{ formatTime(startTime) }}</td>
      </tr>
      <tr>
        <td>Current time</td>
        <td>{{ formatTime(currentTime) }}</td>
      </tr>
      <tr>
        <td>End time</td>
        <td>{{ formatTime(endTime) }}</td>
      </tr>
      <tr>
        <td>Duration</td>
        <td>{{ durationLabel }}</td>
      </tr>
    </table>

    <div v-if="evaluation" style="margin-top: 0.5rem;">
      <span class="text-muted">Evaluation:</span>
      <strong :style="{ color: evaluationColor, marginLeft: '0.25rem' }">
        {{ evaluation }}
      </strong>
    </div>

    <div class="btn-row" style="margin-top: 0.75rem;">
      <button
          type="button"
          class="btn primary"
          @click="start"
          :disabled="isRunning"
      >
        <span class="btn-icon">
          <PlayIcon />
        </span>
        Start soldering
      </button>
      <button
          type="button"
          class="btn"
          @click="stop"
          :disabled="!isRunning"
      >
        <span class="btn-icon">
          <StopIcon />
        </span>
        Stop
      </button>
      <button
          type="button"
          class="btn"
          @click="reset"
          :disabled="!startTime"
      >
        <span class="btn-icon">
          <ArrowPathIcon />
        </span>
        Reset
      </button>
    </div>

    <div class="text-muted" style="margin-top: 0.5rem;">
      Thresholds (test values): &lt;3s = too short, 5–8s = optimal, &gt;12s = too long.
      Later this can be driven by backend profiles.
    </div>
  </div>
</template>
