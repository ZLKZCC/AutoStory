import { http } from "./client";
import type { UserPreferenceInfo } from "./types";

export const getUserPreference = () =>
  http
    .get<{ data: { Preference: UserPreferenceInfo } }>(
      "/autostory/userpreference/current",
    )
    .then((res) => res.data.Preference);

export const updateUserPreference = (data: {
  chunk_model?: boolean;
  chunk_size?: number;
  overlap_size?: number;
}) =>
  http.put<{ data: { Preference: UserPreferenceInfo; Resp: string } }>(
    "/autostory/userpreference/current",
    data,
  );
