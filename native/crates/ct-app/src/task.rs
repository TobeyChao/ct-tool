//! Transport-independent cooperative cancellation for CLI, worker and Web tasks.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

#[derive(Default)]
struct State {
    requested: AtomicBool,
    observed: AtomicBool,
}

#[derive(Clone, Default)]
pub struct CancelFlag(Arc<State>);

impl CancelFlag {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn cancel(&self) {
        self.0.requested.store(true, Ordering::SeqCst);
    }

    pub fn requested(&self) -> bool {
        self.0.requested.load(Ordering::SeqCst)
    }

    pub fn observed(&self) -> bool {
        self.0.observed.load(Ordering::SeqCst)
    }
}

impl crate::export::CancelToken for CancelFlag {
    fn cancelled(&self) -> bool {
        let requested = self.requested();
        if requested {
            self.0.observed.store(true, Ordering::SeqCst);
        }
        requested
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::export::CancelToken;

    #[test]
    fn request_is_not_observed_until_a_safe_checkpoint() {
        let flag = CancelFlag::new();
        let task = flag.clone();
        task.cancel();
        assert!(flag.requested());
        assert!(!flag.observed());
        assert!(CancelToken::cancelled(&flag));
        assert!(task.observed());
    }
}
