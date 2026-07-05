-- Supabase는 pgvector 확장을 관리형으로 이미 켜두므로 마이그레이션에 따로 없다.
-- 로컬 Postgres에서 같은 마이그레이션을 돌리려면 컨테이너 최초 기동 시 켜줘야 한다.
CREATE EXTENSION IF NOT EXISTS vector;
