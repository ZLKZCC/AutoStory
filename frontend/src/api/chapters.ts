import { http } from "./client";
import type { ChapterInfo } from "./types";

interface ChapterShotDTO {
  id: number;
  chapter_title: string;
  chapter_index: number;
  chapter_summary: string;
  content_updated_at?: string;
  word_count?: number;
}

interface ChapterDetailDTO extends ChapterShotDTO {
  chapter_content: string;
}

interface ChapterListResp {
  data: {
    List: ChapterShotDTO[];
    Total: number;
    More: boolean;
  };
}

export const getChapters = async (
  projectId: number,
  page: number = 1,
  pagesize: number = 1000,
): Promise<ChapterInfo[]> => {
  const res = await http.get<ChapterListResp>("/autostory/chapter/chapters", {
    query: { project_id: projectId, page, pagesize },
  });
  const { List = [] } = res.data || {};
  return List.map((c) => ({
    id: c.id,
    title: c.chapter_title,
    chapter_index: c.chapter_index,
    word_count: c.word_count ?? 0,
    content_updated_at: c.content_updated_at,
  }));
};

export const getChapter = async (
  chapterId: number,
): Promise<ChapterInfo> => {
  const res = await http.get<{ data: { Chapter: ChapterDetailDTO } }>(
    `/autostory/chapter/${chapterId}`,
  );
  const c = res.data.Chapter;
  return {
    id: c.id,
    title: c.chapter_title,
    chapter_index: c.chapter_index,
    word_count: (c.chapter_content || "").length,
    content: c.chapter_content,
  };
};

export const createChapterInVolume = async (
  projectId: number,
  volumeId: number,
  title: string = "",
  content: string = "",
): Promise<{ id: number }> => {
  const res = await http.post<{ data: { Chapter: ChapterDetailDTO; Resp: string } }>(
    `/autostory/chapter/add_chapter?project_id=${projectId}&volume_id=${volumeId}`,
    {
      chapter_title: title,
      chapter_index: -1, // 后端按卷尾位置计算
      chapter_summary: "",
      chapter_content: content,
    },
  );
  return { id: res.data.Chapter.id };
};

export const updateChapter = (
  chapterId: number,
  data: { title?: string; content?: string },
) => {
  const body: Record<string, unknown> = {};
  if (data.title !== undefined) body.chapter_title = data.title;
  if (data.content !== undefined) body.chapter_content = data.content;
  return http.put<unknown>(`/autostory/chapter/${chapterId}`, body);
};

export const deleteChapter = (chapterId: number) =>
  http.delete<{ data: { Resp: string } }>(`/autostory/chapter/${chapterId}`);

export const insertChapter = async (
  projectId: number,
  targetChapterId: number,
  position: "before" | "after",
  title: string = "",
  content: string = "",
): Promise<{ id: number }> => {
  const res = await http.post<{ data: { Chapter: ChapterDetailDTO; Resp: string } }>(
    `/autostory/chapter/insert_chapter?project_id=${projectId}&target_chapter_id=${targetChapterId}&position=${position}`,
    {
      chapter_title: title,
      chapter_index: -1, // 后端按插入位置计算
      chapter_summary: "",
      chapter_content: content,
    },
  );
  return { id: res.data.Chapter.id };
};

export const reorderChapters = (
  projectId: number,
  chapterIds: number[],
  movedChapterId?: number,
) =>
  http.put<{ data: { Resp: string } }>(
    `/autostory/chapter/reorder?project_id=${projectId}`,
    {
      chapter_ids: chapterIds,
      ...(movedChapterId !== undefined ? { moved_chapter_id: movedChapterId } : {}),
    },
  );
