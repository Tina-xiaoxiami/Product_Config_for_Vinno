from sqlalchemy import create_engine, inspect

from app.database import Base
import app.models  # noqa: F401 - registers every model on Base.metadata


def test_clean_database_schema_contains_feature_identity_and_document_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    feature_columns = {column["name"] for column in inspector.get_columns("features")}
    assert {
        "config_item_id",
        "primary_cn_name",
        "primary_en_name",
        "identity_status",
    } <= feature_columns
    assert {
        "feature_names",
        "feature_config_item_links",
        "knowledge_documents",
        "registration_import_batches",
        "registration_models",
        "registration_probes",
        "registration_model_probes",
        "product_registration_model_links",
    } <= set(inspector.get_table_names())
    engine.dispose()
