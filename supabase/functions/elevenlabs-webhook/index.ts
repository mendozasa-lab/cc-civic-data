/**
 * elevenlabs-webhook — Supabase Edge Function
 *
 * Receives POST callbacks from ElevenLabs when a speech-to-text transcription
 * completes. Inserts transcript_segments and transcript_entities into Supabase,
 * marks the transcript complete, and dispatches the map_speakers GitHub Actions
 * workflow.
 *
 * Deploy: supabase functions deploy elevenlabs-webhook
 *
 * Required Supabase secrets:
 *   ELEVENLABS_WEBHOOK_SECRET  — from ElevenLabs webhook creation
 *   SUPABASE_SERVICE_ROLE_KEY  — service key (write access)
 *   SUPABASE_URL               — your project URL
 *   GITHUB_PAT                 — fine-grained PAT with actions:write on this repo
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const GITHUB_OWNER = "mendozasa-lab";
const GITHUB_REPO = "cc-civic-data";
const MAP_SPEAKERS_WORKFLOW = "map_speakers.yml";
const COST_PER_HOUR = 0.40;

// ---------------------------------------------------------------------------
// HMAC verification
// ---------------------------------------------------------------------------

async function verifyHmac(secret: string, body: string, signature: string): Promise<boolean> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  const expected = btoa(String.fromCharCode(...new Uint8Array(mac)));
  return signature === expected;
}

// ---------------------------------------------------------------------------
// Words → speaker-turn segments
// ---------------------------------------------------------------------------

interface Word {
  text: string;
  start: number | null;
  end: number | null;
  type: string;
  speaker_id: string | null;
}

interface Segment {
  speaker_label: string;
  start_time: number;
  end_time: number;
  segment_text: string;
  char_start: number; // cumulative char offset in full text (for entity mapping)
  char_end: number;
}

function wordsToSegments(words: Word[]): Segment[] {
  const segments: Segment[] = [];
  let currentSpeaker: string | null = null;
  let currentWords: Word[] = [];
  let charOffset = 0;

  const flush = () => {
    if (!currentWords.length || currentSpeaker === null) return;
    const texts = currentWords.filter(w => w.text).map(w => w.text);
    const text = texts.join(" ").trim();
    if (!text) return;
    const segStart = charOffset;
    charOffset += text.length + 1; // +1 for newline between segments
    segments.push({
      speaker_label: currentSpeaker,
      start_time: currentWords[0].start ?? 0,
      end_time: currentWords[currentWords.length - 1].end ?? 0,
      segment_text: text,
      char_start: segStart,
      char_end: segStart + text.length,
    });
  };

  for (const word of words) {
    const speaker = word.speaker_id;
    if (speaker === null || speaker === undefined) {
      if (currentWords.length) currentWords.push(word);
      continue;
    }
    if (speaker !== currentSpeaker) {
      flush();
      currentSpeaker = speaker;
      currentWords = [word];
    } else {
      currentWords.push(word);
    }
  }
  flush();
  return segments;
}

// ---------------------------------------------------------------------------
// Map entity char offsets → segment_id
// ---------------------------------------------------------------------------

function findSegmentForEntity(
  segments: Segment[],
  segmentIds: number[],
  startChar: number,
  endChar: number,
): number | null {
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    if (startChar >= seg.char_start && endChar <= seg.char_end) {
      return segmentIds[i];
    }
  }
  // Fallback: find segment with most overlap
  let bestId: number | null = null;
  let bestOverlap = 0;
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const overlap = Math.min(endChar, seg.char_end) - Math.max(startChar, seg.char_start);
    if (overlap > bestOverlap) {
      bestOverlap = overlap;
      bestId = segmentIds[i];
    }
  }
  return bestId;
}

// ---------------------------------------------------------------------------
// GitHub Actions dispatch
// ---------------------------------------------------------------------------

async function dispatchMapSpeakers(eventId: number, githubPat: string): Promise<void> {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${MAP_SPEAKERS_WORKFLOW}/dispatches`;
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${githubPat}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs: { event_id: String(eventId) } }),
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`GitHub dispatch failed: ${resp.status} ${body}`);
  }
  console.log(`Dispatched map_speakers workflow for event_id=${eventId}`);
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const webhookSecret = Deno.env.get("ELEVENLABS_WEBHOOK_SECRET");
  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const githubPat = Deno.env.get("GITHUB_PAT");

  // Read body first — needed for both HMAC and parsing
  const body = await req.text();

  // Verify HMAC signature
  if (webhookSecret) {
    const signature = req.headers.get("ElevenLabs-Signature") ?? "";
    const valid = await verifyHmac(webhookSecret, body, signature);
    if (!valid) {
      console.error("Invalid HMAC signature");
      return new Response("Unauthorized", { status: 401 });
    }
  } else {
    console.warn("ELEVENLABS_WEBHOOK_SECRET not set — skipping signature verification");
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(body);
  } catch {
    return new Response("Bad Request: invalid JSON", { status: 400 });
  }

  // Validate payload shape
  const type = payload.type;
  if (type !== "speech_to_text_transcription") {
    console.log(`Ignoring webhook type: ${type}`);
    return new Response("OK", { status: 200 });
  }

  const metadata = (() => {
    try {
      const raw = payload.webhook_metadata as string;
      return raw ? JSON.parse(raw) : {};
    } catch {
      return payload.webhook_metadata ?? {};
    }
  })() as Record<string, unknown>;

  const transcriptId = metadata.transcript_id as number | undefined;
  if (!transcriptId) {
    console.error("Missing transcript_id in webhook_metadata");
    return new Response("Bad Request: missing transcript_id", { status: 400 });
  }

  const transcription = payload.transcription as Record<string, unknown> | undefined;
  if (!transcription) {
    console.error("Missing transcription in payload");
    return new Response("Bad Request: missing transcription", { status: 400 });
  }

  // Return 200 immediately — process async to avoid ElevenLabs retry
  const processPromise = (async () => {
    try {
      const supabase = createClient(supabaseUrl, supabaseKey);

      // Fetch the transcript record to get event_id
      const { data: transcriptRow, error: transcriptErr } = await supabase
        .from("transcripts")
        .select("transcript_id, event_id")
        .eq("transcript_id", transcriptId)
        .single();

      if (transcriptErr || !transcriptRow) {
        console.error(`Transcript ${transcriptId} not found:`, transcriptErr);
        return;
      }

      const eventId = transcriptRow.event_id as number;
      const words = (transcription.words ?? []) as Word[];
      const entities = (transcription.entities ?? []) as Array<{
        text: string;
        entity_type: string;
        start_char: number;
        end_char: number;
      }>;
      const audioDuration = (transcription.audio_duration_secs ?? 0) as number;

      console.log(`Processing transcript_id=${transcriptId} event_id=${eventId}: ${words.length} words, ${entities.length} entities`);

      // Convert words → segments
      const segments = wordsToSegments(words);
      const nonEmptySegments = segments.filter(s => s.segment_text);
      console.log(`Built ${nonEmptySegments.length} speaker-turn segments`);

      if (!nonEmptySegments.length) {
        await supabase.from("transcripts").update({
          status: "error",
          error_message: "No segments produced from ElevenLabs response",
        }).eq("transcript_id", transcriptId);
        return;
      }

      // Insert transcript_segments
      const segmentRows = nonEmptySegments.map(s => ({
        transcript_id: transcriptId,
        event_id: eventId,
        person_id: null,
        speaker_label: s.speaker_label,
        start_time: s.start_time,
        end_time: s.end_time,
        segment_text: s.segment_text,
      }));

      const { data: insertedSegments, error: segErr } = await supabase
        .from("transcript_segments")
        .insert(segmentRows)
        .select("segment_id");

      if (segErr) {
        console.error("Failed to insert segments:", segErr);
        await supabase.from("transcripts").update({
          status: "error",
          error_message: `Segment insert failed: ${segErr.message}`,
        }).eq("transcript_id", transcriptId);
        return;
      }

      const segmentIds = (insertedSegments ?? []).map((r: { segment_id: number }) => r.segment_id);
      console.log(`Inserted ${segmentIds.length} segments`);

      // Insert transcript_entities (map char offsets → segment_id)
      if (entities.length > 0) {
        const entityRows = entities.map(e => ({
          transcript_id: transcriptId,
          event_id: eventId,
          segment_id: findSegmentForEntity(nonEmptySegments, segmentIds, e.start_char, e.end_char),
          entity_text: e.text,
          entity_type: e.entity_type,
          start_char: e.start_char,
          end_char: e.end_char,
        }));

        const { error: entityErr } = await supabase
          .from("transcript_entities")
          .insert(entityRows);

        if (entityErr) {
          console.error("Failed to insert entities:", entityErr);
          // Non-fatal — continue to mark complete
        } else {
          console.log(`Inserted ${entityRows.length} entities`);
        }
      }

      // Mark transcript complete
      const costUsd = Math.round((audioDuration / 3600) * COST_PER_HOUR * 10000) / 10000;
      const { error: updateErr } = await supabase.from("transcripts").update({
        status: "complete",
        completed_at: new Date().toISOString(),
        duration_seconds: audioDuration,
        cost_usd: costUsd,
      }).eq("transcript_id", transcriptId);

      if (updateErr) {
        console.error("Failed to mark transcript complete:", updateErr);
        return;
      }

      console.log(`Transcript ${transcriptId} complete. Duration: ${audioDuration}s, cost: $${costUsd}`);

      // Dispatch map_speakers workflow
      if (githubPat) {
        await dispatchMapSpeakers(eventId, githubPat);
      } else {
        console.warn("GITHUB_PAT not set — skipping map_speakers dispatch");
      }
    } catch (err) {
      console.error("Unhandled error in webhook processing:", err);
    }
  })();

  // @ts-ignore — EdgeRuntime is available in Supabase Edge Functions
  if (typeof EdgeRuntime !== "undefined") {
    // @ts-ignore
    EdgeRuntime.waitUntil(processPromise);
  }

  return new Response("OK", { status: 200 });
});
