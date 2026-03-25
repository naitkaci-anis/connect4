--
-- PostgreSQL database dump
--

\restrict ruWFhu8Sqfl4hZE4ESsmijHLWJSMR8EeEGsbjTIHolfZaiXym7nDm0pA5Xye0Ka

-- Dumped from database version 18.1
-- Dumped by pg_dump version 18.1

-- Started on 2026-02-27 05:50:30

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 220 (class 1259 OID 16582)
-- Name: games; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.games (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    rows integer DEFAULT 9 NOT NULL,
    cols integer DEFAULT 9 NOT NULL,
    starting_color text NOT NULL,
    status text NOT NULL,
    winner text,
    draw boolean DEFAULT false NOT NULL,
    original_sequence text DEFAULT ''::text NOT NULL,
    canonical_key text DEFAULT ''::text NOT NULL,
    source_filename text,
    confiance smallint DEFAULT 1,
    CONSTRAINT chk_games_confiance CHECK (((confiance >= 0) AND (confiance <= 10))),
    CONSTRAINT games_cols_check CHECK (((cols >= 4) AND (cols <= 30))),
    CONSTRAINT games_rows_check CHECK (((rows >= 4) AND (rows <= 30))),
    CONSTRAINT games_starting_color_check CHECK ((starting_color = ANY (ARRAY['R'::text, 'Y'::text]))),
    CONSTRAINT games_status_check CHECK ((status = ANY (ARRAY['IN_PROGRESS'::text, 'FINISHED'::text]))),
    CONSTRAINT games_winner_check CHECK (((winner = ANY (ARRAY['R'::text, 'Y'::text])) OR (winner IS NULL)))
);


ALTER TABLE public.games OWNER TO postgres;

--
-- TOC entry 219 (class 1259 OID 16581)
-- Name: games_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.games_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.games_id_seq OWNER TO postgres;

--
-- TOC entry 5045 (class 0 OID 0)
-- Dependencies: 219
-- Name: games_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.games_id_seq OWNED BY public.games.id;


--
-- TOC entry 221 (class 1259 OID 16608)
-- Name: moves; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.moves (
    game_id integer NOT NULL,
    ply integer NOT NULL,
    col integer NOT NULL,
    "row" integer NOT NULL,
    color text NOT NULL,
    played_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT moves_col_check CHECK ((col >= 0)),
    CONSTRAINT moves_color_check CHECK ((color = ANY (ARRAY['R'::text, 'Y'::text]))),
    CONSTRAINT moves_ply_check CHECK ((ply >= 1)),
    CONSTRAINT moves_row_check CHECK (("row" >= 0))
);


ALTER TABLE public.moves OWNER TO postgres;

--
-- TOC entry 4860 (class 2604 OID 16585)
-- Name: games id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.games ALTER COLUMN id SET DEFAULT nextval('public.games_id_seq'::regclass);


--
-- TOC entry 4880 (class 2606 OID 16607)
-- Name: games games_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_pkey PRIMARY KEY (id);


--
-- TOC entry 4882 (class 2606 OID 16637)
-- Name: games games_source_filename_unique; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_source_filename_unique UNIQUE (source_filename);


--
-- TOC entry 4891 (class 2606 OID 16625)
-- Name: moves moves_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.moves
    ADD CONSTRAINT moves_pkey PRIMARY KEY (game_id, ply);


--
-- TOC entry 4883 (class 1259 OID 16639)
-- Name: games_unique_canonical_all; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX games_unique_canonical_all ON public.games USING btree (rows, cols, starting_color, canonical_key) WHERE (canonical_key IS NOT NULL);


--
-- TOC entry 4884 (class 1259 OID 16634)
-- Name: ix_games_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_games_created_at ON public.games USING btree (created_at DESC);


--
-- TOC entry 4885 (class 1259 OID 16633)
-- Name: ix_games_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_games_status ON public.games USING btree (status);


--
-- TOC entry 4889 (class 1259 OID 16635)
-- Name: ix_moves_game_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_moves_game_id ON public.moves USING btree (game_id);


--
-- TOC entry 4886 (class 1259 OID 16632)
-- Name: uq_finished_canonical; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_finished_canonical ON public.games USING btree (rows, cols, starting_color, canonical_key) WHERE ((status = 'FINISHED'::text) AND (source_filename IS NULL));


--
-- TOC entry 4887 (class 1259 OID 16648)
-- Name: uq_game_canonical; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_game_canonical ON public.games USING btree (rows, cols, starting_color, canonical_key);


--
-- TOC entry 4888 (class 1259 OID 16631)
-- Name: uq_games_source_filename; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_games_source_filename ON public.games USING btree (source_filename) WHERE (source_filename IS NOT NULL);


--
-- TOC entry 4892 (class 2606 OID 16626)
-- Name: moves moves_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.moves
    ADD CONSTRAINT moves_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


-- Completed on 2026-02-27 05:50:30

--
-- PostgreSQL database dump complete
--

\unrestrict ruWFhu8Sqfl4hZE4ESsmijHLWJSMR8EeEGsbjTIHolfZaiXym7nDm0pA5Xye0Ka

