-- A single event store serves the Mini App and the existing Telegram commands.
CREATE TABLE profiles (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    color TEXT NOT NULL DEFAULT '#5b68df',
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX profiles_default_owner ON profiles(owner_id) WHERE is_default;
CREATE TABLE profile_members (
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner','editor','viewer')),
    PRIMARY KEY(profile_id,user_id)
);
ALTER TABLE users ADD COLUMN default_profile_id BIGINT REFERENCES profiles(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN reminders_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN reminder_minutes INTEGER NOT NULL DEFAULT 15 CHECK(reminder_minutes BETWEEN 0 AND 120);
ALTER TABLE users ADD COLUMN evening_time TIME DEFAULT '20:00';
CREATE FUNCTION planner_ensure_profile(uid BIGINT) RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE pid BIGINT;
BEGIN
    SELECT id INTO pid FROM profiles WHERE owner_id=uid AND is_default;
    IF pid IS NULL THEN
        INSERT INTO profiles(owner_id,name,is_default) VALUES(uid,'Моё расписание',true)
        ON CONFLICT(owner_id) WHERE is_default DO UPDATE SET owner_id=EXCLUDED.owner_id
        RETURNING id INTO pid;
    END IF;
    INSERT INTO profile_members(profile_id,user_id,role) VALUES(pid,uid,'owner') ON CONFLICT DO NOTHING;
    UPDATE users SET default_profile_id=pid WHERE id=uid AND default_profile_id IS NULL;
    RETURN pid;
END $$;
CREATE FUNCTION planner_user_created() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM planner_ensure_profile(NEW.id); RETURN NEW; END $$;
CREATE TRIGGER planner_user_created AFTER INSERT ON users FOR EACH ROW EXECUTE FUNCTION planner_user_created();
SELECT planner_ensure_profile(id) FROM users;

CREATE TABLE planner_events (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    weekday SMALLINT NOT NULL CHECK(weekday BETWEEN 1 AND 7),
    type TEXT NOT NULL CHECK(type IN ('lesson','extra')),
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 200),
    start_time TIME NOT NULL,
    end_time TIME NOT NULL CHECK(end_time>start_time),
    location TEXT CHECK(length(location)<=200),
    subtitle TEXT CHECK(length(subtitle)<=1000),
    event_date DATE,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK(event_date IS NULL OR extract(isodow FROM event_date)=weekday)
);
CREATE INDEX planner_events_day ON planner_events(profile_id,weekday,start_time) WHERE deleted_at IS NULL;
CREATE INDEX planner_events_date ON planner_events(profile_id,event_date) WHERE deleted_at IS NULL;
INSERT INTO planner_events(profile_id,weekday,type,label,start_time,end_time,location,subtitle,created_at,updated_at)
SELECT p.id,s.weekday,'lesson',s.subject,s.start_time,s.end_time,s.location,s.teacher,s.created_at,s.updated_at
FROM schedule s JOIN profiles p ON p.owner_id=s.user_id AND p.is_default;
INSERT INTO planner_events(profile_id,weekday,type,label,start_time,end_time,location,subtitle,created_at,updated_at)
SELECT p.id,e.weekday,'extra',e.name,e.start_time,e.end_time,e.location,e.notes,e.created_at,e.updated_at
FROM extras e JOIN profiles p ON p.owner_id=e.user_id AND p.is_default;
ALTER TABLE schedule RENAME TO legacy_schedule;
ALTER TABLE extras RENAME TO legacy_extras;
CREATE VIEW schedule AS SELECT e.id,p.owner_id AS user_id,e.weekday,e.label AS subject,
 e.start_time,e.end_time,e.location,e.subtitle AS teacher,e.created_at,e.updated_at
 FROM planner_events e JOIN profiles p ON p.id=e.profile_id
 WHERE p.is_default AND e.type='lesson' AND e.event_date IS NULL AND e.deleted_at IS NULL;
CREATE VIEW extras AS SELECT e.id,p.owner_id AS user_id,e.label AS name,e.weekday,
 e.start_time,e.end_time,e.location,e.subtitle AS notes,e.created_at,e.updated_at
 FROM planner_events e JOIN profiles p ON p.id=e.profile_id
 WHERE p.is_default AND e.type='extra' AND e.event_date IS NULL AND e.deleted_at IS NULL;
CREATE FUNCTION planner_legacy_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pid BIGINT; ev planner_events; label_value TEXT; subtitle_value TEXT; kind TEXT;
BEGIN
    IF TG_OP='DELETE' THEN
        UPDATE planner_events SET deleted_at=now(),updated_at=now() WHERE id=OLD.id;
        RETURN OLD;
    END IF;
    pid:=planner_ensure_profile(NEW.user_id);
    -- Same profile lock as the new API; legacy and web mutations serialize.
    PERFORM id FROM profiles WHERE id=pid FOR UPDATE;
    IF TG_TABLE_NAME='schedule' THEN
        kind:='lesson'; label_value:=NEW.subject; subtitle_value:=NEW.teacher;
    ELSE
        kind:='extra'; label_value:=NEW.name; subtitle_value:=NEW.notes;
    END IF;
    IF TG_OP='INSERT' THEN
        INSERT INTO planner_events(profile_id,weekday,type,label,start_time,end_time,location,subtitle)
        VALUES(pid,NEW.weekday,kind,label_value,NEW.start_time,NEW.end_time,NEW.location,subtitle_value)
        RETURNING * INTO ev;
    ELSE
        UPDATE planner_events SET weekday=NEW.weekday,label=label_value,start_time=NEW.start_time,
         end_time=NEW.end_time,location=NEW.location,subtitle=subtitle_value,updated_at=now()
         WHERE id=OLD.id RETURNING * INTO ev;
    END IF;
    NEW.id:=ev.id; NEW.created_at:=ev.created_at; NEW.updated_at:=ev.updated_at;
    RETURN NEW;
END $$;
CREATE TRIGGER schedule_write INSTEAD OF INSERT OR UPDATE OR DELETE ON schedule FOR EACH ROW EXECUTE FUNCTION planner_legacy_write();
CREATE TRIGGER extras_write INSTEAD OF INSERT OR UPDATE OR DELETE ON extras FOR EACH ROW EXECUTE FUNCTION planner_legacy_write();

CREATE TABLE event_exceptions (
    event_id BIGINT NOT NULL REFERENCES planner_events(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    cancelled BOOLEAN NOT NULL DEFAULT false,
    label TEXT CHECK(length(label) BETWEEN 1 AND 200),
    type TEXT CHECK(type IN ('lesson','extra')),
    start_time TIME,
    end_time TIME,
    location TEXT CHECK(length(location)<=200),
    subtitle TEXT CHECK(length(subtitle)<=1000),
    PRIMARY KEY(event_id,date),
    CHECK(start_time IS NULL OR end_time IS NULL OR end_time>start_time)
);
CREATE TABLE profile_holidays (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL CHECK(end_date>=start_date),
    types TEXT[] NOT NULL DEFAULT ARRAY['lesson']::TEXT[]
);
CREATE INDEX profile_holidays_dates ON profile_holidays(profile_id,start_date,end_date);
CREATE TABLE planner_tasks (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
    subject TEXT CHECK(length(subject)<=200),
    description TEXT NOT NULL DEFAULT '' CHECK(length(description)<=10000),
    due_date DATE NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT false,
    created_by BIGINT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX planner_tasks_due ON planner_tasks(profile_id,due_date,completed);
CREATE TABLE task_attachments (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES planner_tasks(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size INTEGER NOT NULL CHECK(size BETWEEN 1 AND 5242880),
    data BYTEA NOT NULL CHECK(octet_length(data)=size),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE profile_invites (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('editor','viewer')),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now()+interval '7 days',
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE planner_shares (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    snapshot JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now()+interval '7 days',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE profile_bells (
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL CHECK(position BETWEEN 1 AND 20),
    start_time TIME NOT NULL,
    end_time TIME NOT NULL CHECK(end_time>start_time),
    PRIMARY KEY(profile_id,position)
);
CREATE TABLE reminder_deliveries (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    event_key TEXT NOT NULL,
    delivery_date DATE NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    message_id BIGINT,
    error TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id,profile_id,event_key,delivery_date,kind)
);
