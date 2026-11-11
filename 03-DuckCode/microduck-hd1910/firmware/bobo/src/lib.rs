//! Bobo, the duck's voice call.
//!
//! The reference device opens a socket, says hello, then streams 60 ms Opus frames while
//! it listens and plays the server's Opus while it speaks. This crate is that client.
//! The gamepad only decides *when* — see `padd`, which raises `robot.voice` on the two
//! buttons nothing else uses.

mod audio;
mod identity;
mod machine;
mod protocol;
mod session;

pub use session::{run, SessionConfig};
