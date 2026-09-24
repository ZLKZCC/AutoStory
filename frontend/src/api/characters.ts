import { http, resolveUrl } from "./client";
import type { CharacterInfo, CharacterStageInfo } from "./types";

const CH = "/autostory/character";
const CS = "/autostory/characterstage";

export const listCharacters = (projectId: number) =>
  http
    .get<{ data: { List: CharacterInfo[]; Total: number; More: boolean } }>(
      `${CH}/characters?project_id=${projectId}&page=1&pagesize=1000`,
    )
    .then((res) => res.data.List);

export const createCharacter = (
  projectId: number,
  data: { character_name: string; gender: string; role: string },
) =>
  http
    .post<{ data: { Character: CharacterInfo; Resp: string } }>(
      `${CH}/add_character?project_id=${projectId}`,
      data,
    )
    .then((res) => res.data.Character);

export const getCharacter = (characterId: number) =>
  http
    .get<{ data: { Character: CharacterInfo } }>(`${CH}/${characterId}`)
    .then((res) => res.data.Character);

export const updateCharacter = (
  characterId: number,
  data: Partial<Pick<CharacterInfo, "character_name" | "gender" | "role">>,
) =>
  http.put<CharacterInfo>(`${CH}/${characterId}`, data);

export const deleteCharacter = (characterId: number) =>
  http
    .delete<{ data: { Resp: string } }>(`${CH}/${characterId}`)
    .then((res) => res.data.Resp);

export const listCharacterStages = (characterId: number) =>
  http
    .get<{ data: { List: CharacterStageInfo[]; Total: number; More: boolean } }>(
      `${CS}/characterstages?character_id=${characterId}&page=1&pagesize=1000`,
    )
    .then((res) => res.data.List);

export const createCharacterStage = (
  characterId: number,
  data: Omit<CharacterStageInfo, "id" | "voice_path">,
) =>
  http
    .post<{ data: { CharacterStage: CharacterStageInfo; Resp: string } }>(
      `${CS}/add_characterstage?character_id=${characterId}`,
      data,
    )
    .then((res) => res.data.CharacterStage);

export const updateCharacterStage = (
  stageId: number,
  data: Partial<Omit<CharacterStageInfo, "id">>,
) =>
  http.put<{ data: { CharacterStage: CharacterStageInfo; Resp: string } }>(
    `${CS}/${stageId}`,
    data,
  );

export const deleteCharacterStage = (stageId: number) =>
  http
    .delete<{ data: { Resp: string } }>(`${CS}/${stageId}`)
    .then((res) => res.data.Resp);

export const generateVoiceReference = (
  stageId: number,
  voiceDescription: string,
) =>
  http
    .post<{ data: { TaskId: string; Resp: string } }>(
      `${CS}/generatevoice/${stageId}`,
      { voice_description: voiceDescription },
    )
    .then((res) => res.data);

export const getVoiceGeneratingStatus = () =>
  http.get<{
    data: {
      Generating: boolean;
      StageId: number | null;
      Status: "queued" | "processing" | null;
      Error: string | null;
      Queue: { transient: number; waiting: number; [k: string]: unknown };
    };
  }>(`${CS}/voicegenerating`);

export const getStageVoiceAudioUrl = (stageId: number) =>
  resolveUrl(`${CS}/voice/${stageId}`);

export const deleteStageVoiceReference = (stageId: number) =>
  http
    .delete<{ data: { Resp: string } }>(`${CS}/voice/${stageId}`)
    .then((res) => res.data.Resp);
