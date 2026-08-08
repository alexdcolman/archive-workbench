from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Iterable

from archive_workbench.audiovisual import TimelineAnnotationRow, TranscriptSegmentRow

_COMPONENT_HTML = """
<div class="aw-sync-review">
  <div class="aw-sync-head">
    <div>
      <strong>Revisión sincronizada</strong>
      <div class="aw-sync-time">00:00.000</div>
    </div>
    <div class="aw-sync-state">Buscando reproductor…</div>
  </div>

  <div class="aw-sync-controls">
    <label>
      <span>Hablante actual</span>
      <select class="aw-speaker-select"></select>
    </label>
    <label>
      <span>Otro nombre</span>
      <input class="aw-speaker-input" type="text" placeholder="Ej.: Hablante 1" />
    </label>
    <button type="button" class="aw-speaker-button">Asignar hablante desde aquí</button>

    <label class="aw-note-label">
      <span>Anotación</span>
      <input class="aw-note-input" type="text" placeholder="Ej.: sonríe" />
    </label>
    <button type="button" class="aw-note-button">Agregar anotación aquí</button>
    <div class="aw-local-message" role="status"></div>
  </div>

  <div class="aw-transcript" aria-label="Transcripción sincronizada"></div>
</div>
"""

_COMPONENT_CSS = """
.aw-sync-review {
  font-family: var(--st-font, sans-serif);
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: .55rem;
  background: var(--st-secondary-background-color);
  overflow: hidden;
}
.aw-sync-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .8rem;
  padding: .75rem .85rem .55rem;
  border-bottom: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent);
}
.aw-sync-time { margin-top: .18rem; font-variant-numeric: tabular-nums; font-size: .9rem; opacity: .8; }
.aw-sync-state { font-size: .82rem; opacity: .72; text-align: right; }
.aw-sync-controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: .55rem .65rem;
  padding: .7rem .85rem .75rem;
  border-bottom: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent);
}
.aw-sync-controls label { display: flex; flex-direction: column; gap: .2rem; min-width: 0; }
.aw-sync-controls label span { font-size: .78rem; opacity: .76; }
.aw-sync-controls input, .aw-sync-controls select {
  box-sizing: border-box;
  width: 100%;
  min-height: 2.2rem;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 22%, transparent);
  border-radius: .4rem;
  background: var(--st-background-color);
  color: var(--st-text-color);
  padding: .42rem .5rem;
}
.aw-sync-controls button {
  min-height: 2.25rem;
  border-radius: .42rem;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 22%, transparent);
  background: var(--st-background-color);
  color: var(--st-text-color);
  cursor: pointer;
  align-self: end;
}
.aw-sync-controls button:hover { border-color: var(--st-primary-color); }
.aw-note-label { grid-column: 1 / 2; }
.aw-local-message { grid-column: 1 / -1; min-height: 1.1rem; font-size: .82rem; }
.aw-transcript {
  max-height: 54vh;
  overflow-y: auto;
  padding: .45rem .55rem .75rem;
  scroll-behavior: smooth;
  scrollbar-gutter: stable;
}
.aw-segment {
  padding: .55rem .6rem;
  margin: .18rem 0;
  border-radius: .42rem;
  cursor: pointer;
  border: 1px solid transparent;
}
.aw-segment:hover { border-color: color-mix(in srgb, var(--st-primary-color) 45%, transparent); }
.aw-segment.active {
  border-color: var(--st-primary-color);
  background: color-mix(in srgb, var(--st-primary-color) 11%, transparent);
}
.aw-segment-meta { display: flex; gap: .45rem; align-items: center; margin-bottom: .22rem; font-size: .74rem; opacity: .72; }
.aw-speaker-badge { font-weight: 700; opacity: 1; }
.aw-note-badge { font-style: italic; }
.aw-segment-text { white-space: pre-wrap; line-height: 1.42; }
@media (max-width: 700px) {
  .aw-sync-controls { grid-template-columns: 1fr; }
  .aw-note-label, .aw-local-message { grid-column: 1; }
}
"""

_COMPONENT_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
  const transcript = parentElement.querySelector('.aw-transcript');
  const timeLabel = parentElement.querySelector('.aw-sync-time');
  const stateLabel = parentElement.querySelector('.aw-sync-state');
  const speakerSelect = parentElement.querySelector('.aw-speaker-select');
  const speakerInput = parentElement.querySelector('.aw-speaker-input');
  const speakerButton = parentElement.querySelector('.aw-speaker-button');
  const noteInput = parentElement.querySelector('.aw-note-input');
  const noteButton = parentElement.querySelector('.aw-note-button');
  const message = parentElement.querySelector('.aw-local-message');

  const segments = Array.isArray(data.segments) ? data.segments : [];
  const annotations = Array.isArray(data.annotations) ? data.annotations : [];
  const speakerOptions = Array.isArray(data.speaker_options) ? data.speaker_options : [];

  const formatTime = (seconds) => {
    const value = Math.max(0, Number(seconds || 0));
    const minutes = Math.floor(value / 60);
    const secs = value - minutes * 60;
    return `${String(minutes).padStart(2, '0')}:${secs.toFixed(3).padStart(6, '0')}`;
  };

  const overlap = (mark, segment) => Math.max(
    0,
    Math.min(Number(mark.end_time), Number(segment.end_time)) -
      Math.max(Number(mark.start_time), Number(segment.start_time))
  );

  const speakerForSegment = (segment) => {
    const candidates = annotations
      .filter((mark) => mark.annotation_type === 'speaker' && overlap(mark, segment) > 0)
      .sort((a, b) => overlap(b, segment) - overlap(a, segment));
    return candidates.length ? candidates[0] : null;
  };

  const notesForSegment = (segment) => annotations.filter(
    (mark) => mark.annotation_type === 'annotation' && overlap(mark, segment) > 0
  );

  const rows = [];
  transcript.replaceChildren();
  segments.forEach((segment) => {
    const row = document.createElement('div');
    row.className = 'aw-segment';
    row.dataset.segmentId = String(segment.segment_id);
    row.dataset.startTime = String(segment.start_time);
    row.dataset.endTime = String(segment.end_time);

    const meta = document.createElement('div');
    meta.className = 'aw-segment-meta';
    const timestamp = document.createElement('span');
    timestamp.textContent = `${formatTime(segment.start_time)}–${formatTime(segment.end_time)}`;
    meta.appendChild(timestamp);

    const speaker = speakerForSegment(segment);
    if (speaker) {
      const badge = document.createElement('span');
      badge.className = 'aw-speaker-badge';
      badge.textContent = speaker.label;
      meta.appendChild(badge);
    }
    for (const note of notesForSegment(segment)) {
      const badge = document.createElement('span');
      badge.className = 'aw-note-badge';
      badge.textContent = `[${note.label}]`;
      meta.appendChild(badge);
    }

    const text = document.createElement('div');
    text.className = 'aw-segment-text';
    text.textContent = String(segment.text || '');
    row.appendChild(meta);
    row.appendChild(text);
    transcript.appendChild(row);
    rows.push({element: row, segment});
  });

  speakerSelect.replaceChildren();
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = 'Elegí una persona';
  speakerSelect.appendChild(blank);
  speakerOptions.forEach((option) => {
    const element = document.createElement('option');
    element.value = String(option.value);
    element.textContent = String(option.label);
    speakerSelect.appendChild(element);
  });

  const componentState = parentElement.__awbSyncState || {activeId: null};
  parentElement.__awbSyncState = componentState;

  const findMedia = () => {
    const elements = [...document.querySelectorAll('video, audio')];
    return elements.length ? elements[elements.length - 1] : null;
  };

  let media = findMedia();
  let retryTimer = null;

  const activeSegmentAt = (time) => {
    if (!segments.length) return null;
    const exact = segments.find(
      (segment) => Number(segment.start_time) <= time && time < Number(segment.end_time)
    );
    if (exact) return exact;
    return segments.reduce((best, segment) => {
      const distance = time < Number(segment.start_time)
        ? Number(segment.start_time) - time
        : time - Number(segment.end_time);
      if (!best || distance < best.distance) return {segment, distance};
      return best;
    }, null)?.segment || null;
  };

  const syncSpeakerChoice = (time) => {
    const mark = annotations
      .filter((item) => item.annotation_type === 'speaker' && Number(item.start_time) <= time && time < Number(item.end_time))
      .sort((a, b) => Number(b.start_time) - Number(a.start_time))[0];
    if (!mark || document.activeElement === speakerSelect || document.activeElement === speakerInput) return;
    const matching = speakerOptions.find((option) =>
      (mark.authority_id && option.authority_id === mark.authority_id) ||
      (!mark.authority_id && option.label === mark.label)
    );
    speakerSelect.value = matching ? String(matching.value) : '';
    if (!matching) speakerInput.value = mark.label || '';
  };

  const updateActive = () => {
    if (!media) return;
    const time = Number(media.currentTime || 0);
    timeLabel.textContent = formatTime(time);
    stateLabel.textContent = media.paused ? 'Pausado' : 'Reproduciendo';
    const active = activeSegmentAt(time);
    if (!active) return;
    const changed = componentState.activeId !== active.segment_id;
    componentState.activeId = active.segment_id;
    rows.forEach(({element, segment}) => {
      element.classList.toggle('active', segment.segment_id === active.segment_id);
    });
    if (changed) {
      const row = rows.find(({segment}) => segment.segment_id === active.segment_id)?.element;
      if (row) row.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }
    syncSpeakerChoice(time);
  };

  const bindMedia = () => {
    media = findMedia();
    if (!media) {
      stateLabel.textContent = 'Reproductor no disponible';
      return false;
    }
    stateLabel.textContent = media.paused ? 'Pausado' : 'Reproduciendo';
    media.addEventListener('timeupdate', updateActive);
    media.addEventListener('seeked', updateActive);
    media.addEventListener('play', updateActive);
    media.addEventListener('pause', updateActive);
    updateActive();
    return true;
  };

  if (!bindMedia()) {
    retryTimer = window.setInterval(() => {
      if (bindMedia() && retryTimer) {
        window.clearInterval(retryTimer);
        retryTimer = null;
      }
    }, 300);
  }

  rows.forEach(({element, segment}) => {
    element.onclick = () => {
      media = findMedia();
      if (!media) return;
      media.currentTime = Number(segment.start_time);
      media.pause();
      updateActive();
    };
  });

  const selectedSpeaker = () => speakerOptions.find(
    (option) => String(option.value) === String(speakerSelect.value)
  ) || null;

  const currentTime = () => {
    media = findMedia();
    return media ? Number(media.currentTime || 0) : null;
  };

  const pauseForMark = () => {
    media = findMedia();
    if (media && !media.paused) media.pause();
  };

  speakerButton.onclick = () => {
    const typed = speakerInput.value.trim();
    const selected = selectedSpeaker();
    const label = typed || (selected ? String(selected.label) : '');
    if (!label) {
      message.textContent = 'Elegí o escribí quién está hablando.';
      return;
    }
    pauseForMark();
    const time = currentTime();
    if (time === null) {
      message.textContent = 'No pude leer la posición actual del reproductor.';
      return;
    }
    message.textContent = '';
    setTriggerValue('action', {
      kind: 'speaker',
      time,
      label,
      authority_id: typed ? null : (selected?.authority_id || null),
    });
  };

  const addNote = () => {
    const label = noteInput.value.trim();
    if (!label) {
      message.textContent = 'Escribí la anotación que querés agregar.';
      return;
    }
    pauseForMark();
    const time = currentTime();
    if (time === null) {
      message.textContent = 'No pude leer la posición actual del reproductor.';
      return;
    }
    message.textContent = '';
    setTriggerValue('action', {kind: 'annotation', time, label});
  };
  noteButton.onclick = addNote;
  noteInput.onkeydown = (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      addNote();
    }
  };

  return () => {
    if (retryTimer) window.clearInterval(retryTimer);
    if (media) {
      media.removeEventListener('timeupdate', updateActive);
      media.removeEventListener('seeked', updateActive);
      media.removeEventListener('play', updateActive);
      media.removeEventListener('pause', updateActive);
    }
  };
}
"""


def build_synchronized_review_payload(
    segments: Iterable[TranscriptSegmentRow],
    annotations: Iterable[TimelineAnnotationRow],
    authorities: Iterable[Any],
) -> dict[str, Any]:
    segment_rows = [
        {
            "segment_id": row.segment_id,
            "start_time": float(row.start_time),
            "end_time": float(row.end_time),
            "text": row.text,
        }
        for row in segments
    ]
    annotation_rows = [
        {
            "annotation_id": row.annotation_id,
            "annotation_type": row.annotation_type,
            "start_time": float(row.start_time),
            "end_time": float(row.end_time),
            "label": row.label,
            "authority_id": row.authority_id,
            "authority_name": row.authority_name,
        }
        for row in annotations
    ]

    speaker_options: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str]] = set()
    for authority in authorities:
        label = str(authority.preferred_name)
        key = (str(authority.id), label)
        if key in seen:
            continue
        seen.add(key)
        speaker_options.append(
            {
                "value": f"authority:{authority.id}",
                "label": label,
                "authority_id": str(authority.id),
            }
        )
    for mark in annotation_rows:
        if mark["annotation_type"] != "speaker" or mark["authority_id"]:
            continue
        label = str(mark["label"])
        key = (None, label)
        if key in seen:
            continue
        seen.add(key)
        speaker_options.append(
            {
                "value": f"label:{len(speaker_options)}",
                "label": label,
                "authority_id": None,
            }
        )
    speaker_options.sort(key=lambda row: str(row["label"]).casefold())
    return {
        "segments": segment_rows,
        "annotations": annotation_rows,
        "speaker_options": speaker_options,
    }


@lru_cache(maxsize=1)
def _renderer():
    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_audiovisual_sync_review",
        html=_COMPONENT_HTML,
        css=_COMPONENT_CSS,
        js=_COMPONENT_JS,
    )


def synchronized_media_review(
    segments: list[TranscriptSegmentRow],
    annotations: list[TimelineAnnotationRow],
    authorities: list[Any],
    *,
    key: str,
) -> dict[str, Any] | None:
    renderer = _renderer()
    if renderer is None:
        return None
    result = renderer(
        data=build_synchronized_review_payload(segments, annotations, authorities),
        key=key,
        height=690,
        width="stretch",
        on_action_change=lambda: None,
    )
    action = getattr(result, "action", None)
    return dict(action) if isinstance(action, Mapping) else None
