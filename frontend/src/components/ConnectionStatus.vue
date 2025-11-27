<script setup>
import { computed } from 'vue';

const props = defineProps({
  status: { type: String, default: 'Unknown' },
  level: { type: String, default: 'idle' }, // 'ok' | 'idle' | 'error'
  lastUpdated: { type: Date, required: true },
  latencyMs: { type: Number, default: null },
  error: { type: String, default: null },
  temperatureC: { type: Number, default: null },
  messages: {
    type: Array,
    default: () => [],
  },
});

const formattedTime = computed(() => {
  if (!props.lastUpdated) return '-';
  return props.lastUpdated.toLocaleTimeString();
});

const statusColor = computed(() => {
  switch (props.level) {
    case 'ok':
      return '#22c55e';
    case 'error':
      return '#ef4444';
    default:
      return '#eab308';
  }
});

const temperatureLabel = computed(() => {
  if (props.temperatureC == null) return '—';
  return `${props.temperatureC.toFixed(1)} °C`;
});
</script>

<template>
  <div>
    <p class="status-line">
      Status:
      <strong :style="{ color: statusColor }">
        {{ status }}
      </strong>
    </p>

    <table class="kv-table">
      <tr>
        <td>Last update</td>
        <td>{{ formattedTime }}</td>
      </tr>
      <tr>
        <td>Latency</td>
        <td v-if="latencyMs !== null">{{ latencyMs }} ms</td>
        <td v-else>–</td>
      </tr>
      <tr>
        <td>Tip temperature</td>
        <td>{{ temperatureLabel }}</td>
      </tr>
      <tr>
        <td>Stream quality</td>
        <td>
          <span v-if="level === 'ok'">Good</span>
          <span v-else-if="level === 'idle'">Idle</span>
          <span v-else>Degraded</span>
        </td>
      </tr>
    </table>

    <div v-if="error" class="chip-row" style="margin-top: 0.5rem;">
      <span class="chip">
        ⚠️ {{ error }}
      </span>
    </div>

    <!-- Status messages stack -->
    <div
        v-if="messages && messages.length"
        class="message-stack"
        aria-label="Status messages"
    >
      <div
          v-for="msg in messages"
          :key="msg.id"
          class="message-item"
      >
        <div class="message-meta">
          <span>Message</span>
          <span>{{ new Date(msg.timestamp).toLocaleTimeString() }}</span>
        </div>
        <div class="message-text">
          {{ msg.message }}
        </div>
      </div>
    </div>
  </div>
</template>
