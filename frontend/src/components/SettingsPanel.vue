<script setup>
import { ref, watch } from 'vue';

const props = defineProps({
  initialUrl: { type: String, required: true },
  mode: { type: String, default: 'iframe' } // 'iframe' | 'video'
});

const emit = defineEmits(['update']);

const url = ref(props.initialUrl);
const localMode = ref(props.mode);

watch(
    () => props.initialUrl,
    (val) => {
      url.value = val;
    }
);

watch(
    () => props.mode,
    (val) => {
      localMode.value = val;
    }
);

function applyChanges() {
  emit('update', {
    url: url.value,
    mode: localMode.value
  });
}
</script>

<template>
  <form @submit.prevent="applyChanges">
    <div class="field">
      <label for="url">Stream URL</label>
      <input
          id="url"
          v-model="url"
          type="text"
          autocomplete="off"
          spellcheck="false"
      />
      <div class="text-muted">
        Example: <code>http://192.168.136.100/liveView</code> or a direct MJPEG/HLS URL.
      </div>
    </div>

    <div class="field">
      <label for="mode">Display mode</label>
      <select id="mode" v-model="localMode">
        <option value="iframe">Iframe (entire camera page)</option>
        <option value="video">HTML5 video (direct stream)</option>
      </select>
    </div>

    <div class="btn-row" style="margin-top: 0.75rem;">
      <button type="submit" class="btn primary">
        <span class="btn-icon">💾</span>
        Apply
      </button>
    </div>

    <div style="margin-top: 0.5rem;" class="text-muted">
      Note: browsers may block mixed content (HTTP stream in HTTPS page) or require credentials.
    </div>
  </form>
</template>
