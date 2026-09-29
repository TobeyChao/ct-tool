use ct_storage::publication::FilePublisher;
use ct_test_support::journal_builder::{
    assert_python_publication_recovered, install_python_publication, python_publication_cases,
};

#[test]
fn frozen_python_journals_recover_all_stages_with_content_and_nanosecond_mtime() {
    for case in python_publication_cases() {
        let dir = tempfile::tempdir().unwrap();
        install_python_publication(dir.path(), &case);
        let publisher = FilePublisher::new(dir.path());
        assert!(publisher.recover().unwrap().is_some());
        assert_python_publication_recovered(dir.path(), &case);
        assert!(publisher.recover().unwrap().is_none());
        assert_python_publication_recovered(dir.path(), &case);
    }
}
