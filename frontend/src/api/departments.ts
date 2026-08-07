import { apiClient } from "./client";

export type DepartmentSearchResult = {
  id: number;
  name: string;
  college: string;
  /**
   * 학부제라 세부 전공이 나뉘는 경우의 선택지. "OO과"처럼 학과 자체가 전공
   * 단위면 빈 배열이고, 이때 사용자는 전공을 따로 고르지 않는다.
   */
  majors: string[];
};

/**
 * 학과/학부 자동완성. 회원가입은 로그인 전이라 이 엔드포인트는 인증을 요구하지 않는다.
 *
 * 자유 입력을 그대로 받으면 정식 편제에 없는 이름(예: "경제학부"를 "경제학과"로)이
 * 들어오고, 서버가 "미지정" 단과대 아래에 과목 0개짜리 학과를 새로 만든다. 그
 * 계정은 과목 검색·졸업요건·로드맵 추천이 전부 빈 결과가 된다.
 */
export async function searchDepartments(q: string, limit = 20) {
  const { data } = await apiClient.get<DepartmentSearchResult[]>("/departments/search", {
    params: { q, limit },
  });
  return data;
}
