<script setup>
import { ref } from 'vue';
import SettingsPanel from '../components/SettingsPanel.vue';

const defaultUrl = 'http://192.168.136.100/liveView';

const streamUrl = ref(defaultUrl);
const mode = ref('iframe');

function handleUpdate(payload) {
  if (payload.url !== undefined) {
    streamUrl.value = payload.url || defaultUrl;
  }
  if (payload.mode !== undefined) {
    mode.value = payload.mode;
  }

  // Future integration: send to backend endpoint here
  console.log('Updated settings (test only):', { ...payload });
}
</script>

<template>
  <section class="card">
    <div class="card-header">
      <div>
        <div class="card-title">Camera &amp; stream settings</div>
        <div class="card-subtitle">
          This page will eventually write to the backend. For now it only updates local state.
        </div>
      </div>
    </div>

    <SettingsPanel
        :initial-url="streamUrl"
        :mode="mode"
        @update="handleUpdate"
    />
  </section>
</template>
