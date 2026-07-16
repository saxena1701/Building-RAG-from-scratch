SELECT chunk_id, source_document_id, text, paradedb.score(chunk_id) AS score
                FROM chunks
                WHERE chunk_id @@@ paradedb.match('text', 'Flextrack heart rate chest strap')
                ORDER BY paradedb.score(chunk_id) DESC
                LIMIT 5