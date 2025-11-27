<script setup>
import { onMounted, watch, ref } from 'vue';

const props = defineProps({
  src: { type: String, required: true },
  mode: { type: String, default: 'iframe' }, // 'iframe' | 'video'
  playing: { type: Boolean, default: true },
  reloadKey: { type: Number, default: 0 } // changes to force reload
});

const emit = defineEmits(['error']);

const videoRef = ref(null);

onMounted(() => {
  tryAutoPlay();
});

watch(
    () => [props.playing, props.reloadKey, props.src, props.mode],
    () => {
      if (props.mode === 'video') {
        tryAutoPlay();
      }
    }
);

function tryAutoPlay() {
  if (!videoRef.value) return;
  if (!props.playing) {
    videoRef.value.pause();
    return;
  }

  const playPromise = videoRef.value.play();
  if (playPromise && playPromise.catch) {
    playPromise.catch((err) => {
      console.warn('Autoplay failed', err);
      emit('error', err);
    });
  }
}
</script>

<template>
  <div class="stream-container">
    <div class="stream-inner">
      <!-- IFRAME MODE -->
      <iframe
          v-if="mode === 'iframe'"
          :key="`${mode}-${src}-${reloadKey}`"
          :src="src"
          allowfullscreen
          referrerpolicy="no-referrer"
          @error="emit('error', $event)"
      ></iframe>

      <!-- HTML5 VIDEO MODE (for direct camera streams like .mp4, .m3u8, etc.) -->
      <video
          v-else
          ref="videoRef"
          :key="`${mode}-${src}-${reloadKey}`"
          :src="src"
          :muted="true"
          playsinline
          controls
          @error="emit('error', $event)"
      >
        Your browser does not support the video tag.
      </video>
    </div>
  </div>
</template>
