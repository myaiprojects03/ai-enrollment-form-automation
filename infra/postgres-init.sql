-- Separate databases on one server: the engine (enroll, created by POSTGRES_DB), the mock portals, n8n,
-- and a throwaway database for the backend tests.
CREATE DATABASE portals OWNER enroll;
CREATE DATABASE n8n OWNER enroll;
CREATE DATABASE enroll_test OWNER enroll;
