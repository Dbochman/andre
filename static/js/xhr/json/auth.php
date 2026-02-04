<?php
  /**
   * Gets a token for debugging reasons. This token will be available for 15
   * minutes only and it is for user test_1
   */

  // Initialize the curl object
  $ch = curl_init();
  // Set the url
  // This call will give a new token that will expire aproximately after a week
  // curl_setopt($ch, CURLOPT_URL, "http://user2-squeeze-001.testing.d.spotify.net:8081/user/login/grant?username=test_1&logintokentype=password-reset");
  // This call will have a 15 minute of lifetime
  curl_setopt($ch, CURLOPT_URL, "http://user2-squeeze-001.testing.d.spotify.net:8081/user/login/grant?username=test_1&logintokentype=login");
  curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
  // Get the response
  $output = curl_exec($ch);
  // Close the curl object
  curl_close($ch);
  // Convert the response to an xml object
  $xml = new SimpleXMLElement($output);
  $response = json_decode(json_encode($xml), true);

  // Get the token
  $array['status'] = 0;
  $array['token'] = $response['token'];
  $array['expires'] = 15 * 60; //15 minutes
  echo json_encode($array);
?>
