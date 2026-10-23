"""PostgreSQL guards complement API checks and composite learning foreign keys."""
from sqlalchemy import text


def install_ownership_guards(conn):
    if conn.dialect.name != "postgresql":
        return
    conn.execute(text("""
        CREATE OR REPLACE FUNCTION learning.check_question_owner() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM content.questions q WHERE q.id = NEW.question_id
                           AND (q.owner_user_id IS NULL OR q.owner_user_id = NEW.user_id)) THEN
                RAISE EXCEPTION 'question ownership mismatch' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """))
    conn.execute(text("DROP TRIGGER IF EXISTS question_owner_guard ON learning.question_access"))
    conn.execute(text("""CREATE TRIGGER question_owner_guard BEFORE INSERT OR UPDATE ON learning.question_access
                        FOR EACH ROW EXECUTE FUNCTION learning.check_question_owner()"""))
