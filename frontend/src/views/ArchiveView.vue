<script setup>
import { ref, computed } from 'vue';

const clips = ref([
  {
    id: 1,
    timestamp: new Date(Date.now() - 1000 * 60 * 5),
    chipType: 'QFP-64',
    durationSec: 6.4,
  },
  {
    id: 2,
    timestamp: new Date(Date.now() - 1000 * 60 * 60),
    chipType: 'BGA-256',
    durationSec: 11.2,
  },
  {
    id: 3,
    timestamp: new Date(Date.now() - 1000 * 60 * 60 * 4),
    chipType: 'SOIC-8',
    durationSec: 3.2,
  },
  {
    id: 4,
    timestamp: new Date(Date.now() - 1000 * 60 * 60 * 24),
    chipType: 'QFN-32',
    durationSec: 7.8,
  },
]);

const sortedClips = computed(() =>
    [...clips.value].sort(
        (a, b) => b.timestamp.getTime() - a.timestamp.getTime(),
    ),
);

function formatTimestamp(date) {
  return date.toLocaleString();
}

function formatDuration(sec) {
  return `${sec.toFixed(1)} s`;
}

// Test button simulating a backend refresh
function testReloadArchive() {
  clips.value = clips.value.map((clip) => ({
    ...clip,
    durationSec: clip.durationSec + (Math.random() * 2 - 1),
  }));
}
</script>

<template>
  <section class="card" aria-label="Soldering archive">
    <div class="card-header">
      <div>
        <div class="card-title">Archive</div>
        <div class="card-subtitle">
          Saved soldering clips (fake data for now). Later this will come from the backend.
        </div>
      </div>
      <div class="btn-row">
        <button class="btn primary" type="button" @click="testReloadArchive">
          <span class="btn-icon">🔁</span>
          Test reload from backend
        </button>
      </div>
    </div>

    <table class="archive-list">
      <thead>
      <tr>
        <th>Timestamp</th>
        <th>Chip type</th>
        <th>Duration</th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="clip in sortedClips" :key="clip.id">
        <td>{{ formatTimestamp(clip.timestamp) }}</td>
        <td>{{ clip.chipType }}</td>
        <td>{{ formatDuration(clip.durationSec) }}</td>
      </tr>
      </tbody>
    </table>
  </section>
</template>
